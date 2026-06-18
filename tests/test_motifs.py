"""Tests for the heuristic tactical-motif detectors (no engine needed)."""

from __future__ import annotations

import chess

from chess_coach_mcp import motifs


def test_winning_captures_finds_hanging_knight(fens):
    board = chess.Board(fens["hanging_knight"])  # Black to move, ...fxe5
    caps = motifs.winning_captures(board, min_gain=2)
    assert caps, "expected a winning capture"
    top = caps[0]
    assert top["to"] == "e5"
    assert top["victim"] == "knight"
    assert top["gain"] == 3


def test_winning_captures_empty_when_nothing_hanging():
    board = chess.Board()  # start position, no captures at all
    assert motifs.winning_captures(board) == []


def test_detect_fork_knight_forks_king_and_rook(fens):
    board = chess.Board(fens["knight_fork"])
    forks = motifs.detect_fork(board, chess.WHITE)
    assert forks, "expected a fork"
    assert forks[0]["square"] == "f7"
    assert set(forks[0]["targets"]) == {"h8", "d8"}


def test_detect_fork_ignores_low_value_double_attack():
    # White queen on d4 'attacks' two pawns — not a fork (queen worth more).
    board = chess.Board("4k3/8/8/8/3Q4/8/2p1p3/4K3 w - - 0 1")
    assert motifs.detect_fork(board, chess.WHITE) == []


def test_detect_pins(fens):
    board = chess.Board(fens["pin"])  # Bb5 pins Nc6 to Ke8
    pins = motifs.detect_pins(board, chess.WHITE)
    assert any(p["square"] == "c6" for p in pins)


def test_back_rank_weakness(fens):
    blocked = chess.Board(fens["back_rank"])
    assert motifs.back_rank_weakness(blocked, chess.WHITE) is True

    luft = chess.Board(fens["back_rank_luft"])
    assert motifs.back_rank_weakness(luft, chess.WHITE) is False


def test_tags_for_move_passes_through_mate_flags():
    before = chess.Board()
    after = before.copy()
    after.push(chess.Move.from_uci("e2e4"))
    tags = motifs.tags_for_move(
        before, after, mover=chess.WHITE, is_error=False,
        missed_mate=True, allowed_mate=True,
    )
    names = {t["motif"] for t in tags}
    assert motifs.models.MOTIF_MISSED_MATE in names
    assert motifs.models.MOTIF_ALLOWED_MATE in names
    # Bilingual label is attached.
    for t in tags:
        assert t["motif_ko"]


def test_tags_for_move_flags_hanging_after_blunder():
    # White Nf3 plays Ne5??, hanging the knight to the f6 pawn (...fxe5).
    before = chess.Board("4k3/8/5p2/8/8/5N2/8/4K3 w - - 0 1")
    after = before.copy()
    after.push(chess.Move.from_uci("f3e5"))
    tags = motifs.tags_for_move(
        before, after, mover=chess.WHITE, is_error=True,
        missed_mate=False, allowed_mate=False,
    )
    assert any(t["motif"] == motifs.models.MOTIF_HANGING for t in tags)
