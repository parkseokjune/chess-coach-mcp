"""Shared pytest fixtures, sample data, and engine gating.

Tests marked ``engine`` are skipped automatically when no Stockfish binary is
available, so the suite still runs (minus those) on a machine without it.
"""

from __future__ import annotations

import json

import chess
import pytest

from chess_coach_mcp.config import find_stockfish
from chess_coach_mcp.engine import StockfishEngine

# --- Sample games ----------------------------------------------------------
# Scholar's mate: Black (testuser) blunders 3...Nf6 allowing 4.Qxf7#.
SCHOLAR_MATE_PGN = """[Event "Test"]
[White "Opponent"]
[Black "testuser"]
[Result "1-0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0
"""

# Fool's mate: White (testuser) blunders 2.g4 allowing 2...Qh4#.
FOOLS_MATE_PGN = """[Event "Test"]
[White "testuser"]
[Black "Opponent"]
[Result "0-1"]

1. f3 e5 2. g4 Qh4# 0-1
"""

# --- Sample positions ------------------------------------------------------
FENS = {
    # White: Ra1, Kg1; Black: Kg8 with f7/g7/h7 pawns. 1.Ra8# is mate.
    "mate_in_1": "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1",
    # Black to move; ...fxe5 wins the undefended knight.
    "hanging_knight": "4k3/8/5p2/4N3/8/8/8/4K3 b - - 0 1",
    # White Nf7 forks Black Kh8 and Rd8.
    "knight_fork": "3r3k/5N2/8/8/8/8/8/4K3 w - - 0 1",
    # White Bb5 pins Black Nc6 to Ke8.
    "pin": "4k3/8/2n5/1B6/8/8/8/4K3 b - - 0 1",
    # White king on back rank, f2/g2/h2 pawns, Black rook on a1: back-rank risk.
    "back_rank": "6k1/8/8/8/8/8/5PPP/r5K1 w - - 0 1",
    # Same but h-pawn pushed to h3 giving the king luft.
    "back_rank_luft": "6k1/8/8/8/8/7P/5PP1/r5K1 w - - 0 1",
    "startpos": chess.STARTING_FEN,
    # King + rook vs king: an endgame by material.
    "kr_endgame": "8/8/8/4k3/8/8/4K3/4R3 w - - 0 1",
}


@pytest.fixture
def fens():
    return FENS


@pytest.fixture
def scholar_pgn():
    return SCHOLAR_MATE_PGN


@pytest.fixture
def fools_pgn():
    return FOOLS_MATE_PGN


# --- Source payload builders ----------------------------------------------

@pytest.fixture
def lichess_game():
    """Build one Lichess NDJSON game object with a chosen user/colour/result."""

    def build(pgn: str, *, user: str, user_color: str, winner: str | None,
              opening: str = "King's Pawn Game", eco: str = "C20") -> dict:
        white = user if user_color == "white" else "Opponent"
        black = user if user_color == "black" else "Opponent"
        return {
            "id": "g" + str(abs(hash((pgn, user_color))) % 100000),
            "rated": True,
            "variant": "standard",
            "speed": "blitz",
            "perf": "blitz",
            "createdAt": 1700000000000,
            "status": "mate",
            "winner": winner,
            "players": {
                "white": {"user": {"name": white}, "rating": 1500},
                "black": {"user": {"name": black}, "rating": 1490},
            },
            "opening": {"eco": eco, "name": opening},
            "clock": {"initial": 300, "increment": 0},
            "pgn": pgn,
        }

    return build


@pytest.fixture
def lichess_ndjson():
    def build(games: list[dict]) -> str:
        return "\n".join(json.dumps(g) for g in games)

    return build


@pytest.fixture
def chesscom_game():
    def build(pgn: str, *, user: str, user_color: str, result_pair: tuple[str, str],
              url: str = "https://www.chess.com/game/live/123") -> dict:
        white = user if user_color == "white" else "Opponent"
        black = user if user_color == "black" else "Opponent"
        w_res, b_res = result_pair
        return {
            "url": url,
            "uuid": "abc-123",
            "pgn": pgn,
            "time_control": "300",
            "time_class": "blitz",
            "rules": "chess",
            "end_time": 1700000000,
            "eco": "https://www.chess.com/openings/Kings-Pawn-Opening",
            "white": {"username": white, "rating": 1500, "result": w_res},
            "black": {"username": black, "rating": 1490, "result": b_res},
        }

    return build


# --- Engine gating + cleanup ----------------------------------------------

def pytest_collection_modifyitems(config, items):
    if find_stockfish() is None:
        skip_engine = pytest.mark.skip(reason="Stockfish binary not installed")
        for item in items:
            if "engine" in item.keywords:
                item.add_marker(skip_engine)


@pytest.fixture(scope="session", autouse=True)
def _shutdown_engine():
    yield
    StockfishEngine.reset()
