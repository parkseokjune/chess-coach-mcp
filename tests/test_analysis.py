"""Tests for the analysis pipeline (phase, classification, game review)."""

from __future__ import annotations

import io

import chess
import chess.pgn
import pytest

from chess_coach_mcp import analysis, models


def test_detect_phase(fens):
    assert analysis.detect_phase(chess.Board(fens["startpos"])) == models.PHASE_OPENING
    assert analysis.detect_phase(chess.Board(fens["kr_endgame"])) == models.PHASE_ENDGAME


def test_classify_thresholds():
    assert analysis._classify(0.0, is_best=True) == models.BEST
    assert analysis._classify(3.0, is_best=False) == models.GOOD
    assert analysis._classify(7.0, is_best=False) == models.INACCURACY
    assert analysis._classify(12.0, is_best=False) == models.MISTAKE
    assert analysis._classify(25.0, is_best=False) == models.BLUNDER
    # A best move with a small numeric drop is still 'best'.
    assert analysis._classify(2.0, is_best=True) == models.BEST


def test_analyze_position_invalid_fen():
    with pytest.raises(ValueError):
        analysis.analyze_position("not a fen")


def test_analyze_position_terminal_short_circuits(fools_pgn):
    game = chess.pgn.read_game(io.StringIO(fools_pgn))
    final = game.end().board()
    assert final.is_checkmate()
    res = analysis.analyze_position(final.fen())  # no engine call needed
    assert res["game_over"] is True
    assert res["is_checkmate"] is True
    assert res["side_to_move"] == "white"


@pytest.mark.engine
def test_analyze_position_mate(fens):
    res = analysis.analyze_position(fens["mate_in_1"], depth=12, multipv=2)
    assert res["game_over"] is False
    assert res["best_line"]["move_san"] == "Ra8#"
    assert res["eval_mate"] == 1
    assert res["win_pct_side_to_move"] > 99.0


@pytest.mark.engine
def test_analyze_game_detects_blunder_and_mate(scholar_pgn):
    report = analysis.analyze_game(scholar_pgn, depth=10, user_color="black")
    assert report["total_plies"] == 7
    assert len(report["moves"]) == 7
    assert report["result"] == "1-0"

    # Black blundered 3...Nf6 allowing mate.
    assert report["summary"]["black"][models.BLUNDER] >= 1
    motif_names = set()
    for wm in report["worst_moments"]:
        for t in wm["motifs"]:
            motif_names.add(t["motif"])
    assert models.MOTIF_ALLOWED_MATE in motif_names

    # Structural guarantees relied on by diagnose/drills.
    assert report["summary"]["by_phase"]
    for wm in report["worst_moments"]:
        assert wm["fen_before"]
        assert wm["classification"] in (models.MISTAKE, models.BLUNDER)


@pytest.mark.engine
def test_analyze_game_move_fields(scholar_pgn):
    report = analysis.analyze_game(scholar_pgn, depth=8, user_color="black")
    m = report["moves"][0]
    for key in (
        "ply", "san", "uci", "classification", "classification_ko",
        "win_before", "win_after", "win_drop", "cp_loss", "best_move_san",
        "phase", "phase_ko", "fen_before", "accuracy",
    ):
        assert key in m
    assert m["classification_ko"] == models.CLASS_KO[m["classification"]]


def test_analyze_game_empty_pgn_raises():
    # read_game returns None only at EOF / empty input.
    with pytest.raises(ValueError):
        analysis.analyze_game("", depth=6)
