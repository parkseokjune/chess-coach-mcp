"""Tests for text board rendering + Lichess links (pure, no engine)."""

from __future__ import annotations

import chess
import pytest

from chess_coach_mcp import analysis, render, server


def test_lichess_analysis_url():
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    url = render.lichess_analysis_url(fen)
    assert url.startswith("https://lichess.org/analysis/")
    assert " " not in url
    assert "_w_KQkq_" in url


def test_board_text_startpos_white():
    txt = render.board_text(chess.STARTING_FEN, unicode=False, orientation="white")
    lines = txt.splitlines()
    assert lines[0].startswith("8 r n b q k b n r")
    assert lines[-2].startswith("1 R N B Q K B N R")
    assert lines[-1].strip().split() == list("abcdefgh")


def test_board_text_black_orientation_flips_files():
    txt = render.board_text(chess.STARTING_FEN, orientation="black")
    assert txt.splitlines()[-1].strip().split() == list("hgfedcba")


def test_render_bundle_keys():
    r = render.render(chess.STARTING_FEN)
    assert set(r) >= {
        "fen", "side_to_move", "orientation", "ascii", "unicode", "lichess_url"
    }
    assert r["side_to_move"] == "white"
    assert "♜" in r["unicode"]  # unicode variant uses glyphs
    assert "r" in r["ascii"]    # ascii variant uses letters


def test_render_invalid_fen_raises():
    with pytest.raises(ValueError):
        render.render("not-a-fen")


def test_render_board_tool_ok():
    res = server.render_board(chess.STARTING_FEN)
    assert "ascii" in res
    assert res["lichess_url"].startswith("https://lichess.org/analysis/")


def test_render_board_tool_bad_fen_returns_error():
    res = server.render_board("nope")
    assert "error" in res


@pytest.mark.engine
def test_analyze_position_includes_board_and_url(fens):
    res = analysis.analyze_position(fens["mate_in_1"], depth=8, multipv=1)
    assert res["lichess_url"].startswith("https://lichess.org/analysis/")
    assert res["board_ascii"]
    assert "8" in res["board_ascii"]  # has rank labels
