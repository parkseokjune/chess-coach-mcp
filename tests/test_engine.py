"""Tests for the evaluation math and the Stockfish wrapper."""

from __future__ import annotations

import chess
import pytest

from chess_coach_mcp.engine import (
    EngineError,
    StockfishEngine,
    move_accuracy,
    win_percent,
)


def test_win_percent_bounds_and_monotonic():
    assert win_percent(0) == pytest.approx(50.0, abs=0.5)
    assert win_percent(-1000) < win_percent(0) < win_percent(1000)
    assert 0.0 <= win_percent(-10000) < 1.0
    assert 99.0 < win_percent(10000) <= 100.0


def test_move_accuracy_decreases_with_loss():
    assert move_accuracy(60.0, 60.0) == pytest.approx(100.0, abs=0.5)
    assert move_accuracy(60.0, 60.0) > move_accuracy(60.0, 45.0)
    assert move_accuracy(60.0, 45.0) > move_accuracy(60.0, 10.0)
    assert 0.0 <= move_accuracy(95.0, 5.0) <= 100.0


@pytest.mark.engine
def test_evaluate_finds_mate_in_one(fens):
    eng = StockfishEngine.get()
    board = chess.Board(fens["mate_in_1"])
    ev = eng.evaluate(board, depth=12, multipv=1)
    assert ev.mate == 1
    assert ev.best_move == "a1a8"
    assert ev.win_pct > 99.0


@pytest.mark.engine
def test_evaluate_multipv_returns_multiple_lines(fens):
    eng = StockfishEngine.get()
    board = chess.Board(fens["mate_in_1"])
    ev = eng.evaluate(board, depth=10, multipv=3)
    assert len(ev.lines) >= 2
    # Lines are ordered best-first.
    assert ev.lines[0]["cp"] >= ev.lines[1]["cp"]


@pytest.mark.engine
def test_evaluate_rejects_terminal_position():
    board = chess.Board("6k1/8/8/8/8/8/8/R5K1 b - - 0 1")  # not terminal
    # Construct a stalemate: black king a8, white Kc7? build a real stalemate.
    stalemate = chess.Board("k7/8/1Q6/8/8/8/8/7K b - - 0 1")
    assert stalemate.is_stalemate()
    eng = StockfishEngine.get()
    with pytest.raises(EngineError):
        eng.evaluate(stalemate, depth=5)


@pytest.mark.engine
def test_engine_is_singleton():
    a = StockfishEngine.get()
    b = StockfishEngine.get()
    assert a is b
