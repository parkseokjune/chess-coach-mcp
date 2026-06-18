"""Tests for game-source fetchers using mocked HTTP (no live network)."""

from __future__ import annotations

import re

import pytest

from chess_coach_mcp import sources
from chess_coach_mcp.sources import SourceError


async def test_fetch_lichess_games(httpx_mock, lichess_game, lichess_ndjson, scholar_pgn):
    game = lichess_game(
        scholar_pgn, user="testuser", user_color="black", winner="white"
    )
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
        text=lichess_ndjson([game]),
    )
    records = await sources.fetch_lichess_games("testuser", 5)
    assert len(records) == 1
    rec = records[0]
    assert rec.source == "lichess"
    assert rec.white == "Opponent"
    assert rec.black == "testuser"
    assert rec.result == "1-0"
    assert rec.color_of("testuser") == "black"
    assert rec.pgn.strip().endswith("1-0")
    assert rec.opening == "King's Pawn Game"


async def test_fetch_lichess_404(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"), status_code=404
    )
    with pytest.raises(SourceError):
        await sources.fetch_lichess_games("ghost", 5)


async def test_fetch_chesscom_games(httpx_mock, chesscom_game, fools_pgn):
    archive_url = "https://api.chess.com/pub/player/testuser/games/2024/06"
    httpx_mock.add_response(
        url=re.compile(r".*/pub/player/testuser/games/archives$"),
        json={"archives": [archive_url]},
    )
    game = chesscom_game(
        fools_pgn, user="testuser", user_color="white",
        result_pair=("checkmated", "win"),
    )
    httpx_mock.add_response(url=archive_url, json={"games": [game]})

    records = await sources.fetch_chesscom_games("testuser", 5)
    assert len(records) == 1
    rec = records[0]
    assert rec.source == "chesscom"
    assert rec.white == "testuser"
    assert rec.result == "0-1"  # black won (white was checkmated)
    assert rec.color_of("testuser") == "white"


async def test_fetch_chesscom_404(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*/pub/player/ghost/games/archives$"), status_code=404
    )
    with pytest.raises(SourceError):
        await sources.fetch_chesscom_games("ghost", 5)


async def test_fetch_games_dispatch_unknown_source():
    with pytest.raises(SourceError):
        await sources.fetch_games("x", source="bogus")


async def test_fetch_daily_puzzle(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*/api/puzzle/daily"),
        json={
            "game": {"pgn": "e4 e5 Nf3 Nc6"},
            "puzzle": {
                "id": "abcde",
                "rating": 1400,
                "themes": ["fork", "short"],
                "initialPly": 2,
                "solution": ["f1c4", "g8f6"],
            },
        },
    )
    puzzle = await sources.fetch_daily_puzzle()
    assert puzzle["id"] == "abcde"
    assert puzzle["side_to_move"] == "white"  # after e4 e5 (2 plies)
    assert puzzle["solution"][0] == "f1c4"
    assert puzzle["fen"]
    assert puzzle["url"].endswith("abcde")
