"""Regression tests for defects found by the adversarial review pass.

Each test maps to one confirmed finding so the fix can't silently regress.
"""

from __future__ import annotations

import json
import re

import chess
import httpx
import pytest

from chess_coach_mcp import analysis, diagnose, drills, models, motifs, sources
from chess_coach_mcp.engine import EngineError, StockfishEngine
from chess_coach_mcp.sources import SourceError


# --- Finding: found-but-broken Stockfish binary -> EngineError --------------

def test_broken_engine_binary_raises_engine_error():
    # /bin/echo exists and is executable but is not a UCI engine.
    with pytest.raises(EngineError):
        StockfishEngine("/bin/echo", threads=1, hash_mb=16)


# --- Finding: transport / JSON errors must surface as SourceError -----------

async def test_lichess_network_error_becomes_source_error(httpx_mock):
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
    )
    with pytest.raises(SourceError):
        await sources.fetch_lichess_games("someone", 5)


async def test_lichess_malformed_ndjson_becomes_source_error(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
        text="{ this is not valid json\n",
    )
    with pytest.raises(SourceError):
        await sources.fetch_lichess_games("someone", 5)


async def test_chesscom_non_json_archive_becomes_source_error(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*/pub/player/someone/games/archives$"),
        text="<html>down for maintenance</html>",
        status_code=200,
    )
    with pytest.raises(SourceError):
        await sources.fetch_chesscom_games("someone", 5)


# --- Finding: Lichess aborted/no-winner games must not be draws -------------

def test_lichess_aborted_game_is_unknown_not_draw():
    obj = {
        "id": "abc",
        "status": "aborted",
        "winner": None,
        "players": {
            "white": {"user": {"name": "a"}, "rating": 1500},
            "black": {"user": {"name": "b"}, "rating": 1500},
        },
        "pgn": "",
    }
    rec = sources._lichess_record(obj)
    assert rec.result == "*"


def test_lichess_real_draw_still_maps_to_draw():
    obj = {
        "id": "abc",
        "status": "draw",
        "winner": None,
        "players": {
            "white": {"user": {"name": "a"}},
            "black": {"user": {"name": "b"}},
        },
        "pgn": "",
    }
    assert sources._lichess_record(obj).result == "1/2-1/2"


# --- Finding: detect_fork must skip pinned forkers --------------------------

def test_detect_fork_skips_pinned_forker():
    # White Ne4 is absolutely pinned by Re8 to Ke1; it cannot really fork.
    board = chess.Board("4r3/8/3q1n2/8/4N3/8/8/4K3 w - - 0 1")
    assert board.is_pinned(chess.WHITE, chess.E4)
    assert motifs.detect_fork(board, chess.WHITE) == []


# --- Finding: negative max_plies must not slice from the end ----------------

@pytest.mark.engine
def test_negative_max_plies_is_clamped(scholar_pgn):
    report = analysis.analyze_game(scholar_pgn, depth=8, max_plies=-2)
    # Clamped to 0 (truncated), NOT moves[:-2] which would keep 5 plies.
    assert report["truncated"] is True
    assert report["total_plies"] == 0
    assert report["moves"] == []


# --- Finding: delivering checkmate must not be flagged missed_mate ----------

@pytest.mark.engine
def test_delivering_mate_is_not_missed_mate(scholar_pgn):
    report = analysis.analyze_game(scholar_pgn, depth=10, user_color="white")
    # White delivers Qxf7# on the last ply; that must not be 'missed_mate'.
    mating = report["moves"][-1]
    assert mating["san"].startswith("Qxf7")
    assert all(t["motif"] != models.MOTIF_MISSED_MATE for t in mating["motifs"])
    # And it must not pollute the white-focused motif counts.
    assert models.MOTIF_MISSED_MATE not in report["motif_counts"]


# --- Finding: empty puzzle solution must not discard the bonus puzzle -------

@pytest.mark.engine
async def test_empty_puzzle_solution_keeps_bonus(
    httpx_mock, lichess_game, lichess_ndjson, scholar_pgn
):
    games = [
        lichess_game(scholar_pgn, user="testuser", user_color="black", winner="white"),
    ]
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
        text=lichess_ndjson(games),
    )
    httpx_mock.add_response(
        url=re.compile(r".*/api/puzzle/daily"),
        json={
            "game": {"pgn": "e4 e5"},
            "puzzle": {"id": "noSol", "rating": 1500, "themes": [],
                       "initialPly": 2, "solution": []},  # empty solution
        },
    )
    result = await drills.recommend_drills(
        "testuser", source="lichess", max_games=5, depth=8, num_drills=3
    )
    assert result["bonus_puzzle"] is not None
    assert result["bonus_puzzle"]["answer_uci"] is None
    assert result["bonus_puzzle"]["fen"]


# --- Finding (round 2): late_blunder_rate population mismatch ---------------

def _fake_report_with_many_late_blunders(pgn, *, depth=None, user_color=None,
                                         max_plies=None, engine=None):
    """A game with 2 early + 8 late user blunders, but worst_moments capped at 6.

    The old code counted late blunders from the capped worst_moments, so the
    numerator could never exceed 6 even though total_blunders counts all 10.
    """
    color = user_color
    other = "black" if color == "white" else "white"
    moves = [{"side": color, "classification": models.BLUNDER, "move_number": n}
             for n in (10, 20)]  # 2 early (must NOT be counted as late)
    moves += [{"side": color, "classification": models.BLUNDER, "move_number": n}
              for n in range(31, 39)]  # 8 late
    moves.append({"side": other, "classification": models.BLUNDER, "move_number": 35})  # opp, ignore

    user_stats = {m: 0 for m in models.CLASS_SEVERITY}
    user_stats.update({"moves": 40, "acpl": 50.0, "accuracy": 70.0, models.BLUNDER: 10})
    opp_stats = {m: 0 for m in models.CLASS_SEVERITY}
    opp_stats.update({"moves": 40, "acpl": 30.0, "accuracy": 80.0})

    worst = [
        {"classification": models.BLUNDER, "move_number": 31 + i, "motifs": [],
         "fen_before": "8/8/8/8/8/8/8/K6k w - - 0 1", "best_move_san": "Kb1",
         "san": "Ka1", "win_drop": 30.0, "side": color}
        for i in range(6)  # capped — fewer than the 10 real blunders
    ]
    return {
        "summary": {
            "white": user_stats if color == "white" else opp_stats,
            "black": user_stats if color == "black" else opp_stats,
            "by_phase": {},
        },
        "motif_counts": {},
        "moves": moves,
        "worst_moments": worst,
    }


async def test_late_blunder_rate_uses_full_population(
    httpx_mock, monkeypatch, lichess_game, lichess_ndjson, scholar_pgn
):
    monkeypatch.setattr(diagnose, "analyze_game", _fake_report_with_many_late_blunders)

    class _FakeEngine:
        @staticmethod
        def get():
            return object()

    monkeypatch.setattr(diagnose, "StockfishEngine", _FakeEngine)

    games = [
        lichess_game(scholar_pgn, user="testuser", user_color="white", winner="white"),
    ]
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
        text=lichess_ndjson(games),
    )
    result = await diagnose.diagnose_weaknesses("testuser", source="lichess", depth=8)
    tt = result["time_trouble_proxy"]
    assert tt["total_blunders"] == 10
    assert tt["late_blunders"] == 8  # all 8 late, NOT capped at 6
    assert tt["late_blunder_rate"] == 0.8
