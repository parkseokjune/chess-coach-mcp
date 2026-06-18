"""Tests for drill recommendation (mocked HTTP + real engine)."""

from __future__ import annotations

import re

import pytest

from chess_coach_mcp import drills


@pytest.mark.engine
async def test_recommend_drills_from_own_blunders(
    httpx_mock, lichess_game, lichess_ndjson, scholar_pgn, fools_pgn
):
    games = [
        lichess_game(scholar_pgn, user="testuser", user_color="black", winner="white"),
        lichess_game(fools_pgn, user="testuser", user_color="white", winner="black"),
    ]
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
        text=lichess_ndjson(games),
    )
    httpx_mock.add_response(
        url=re.compile(r".*/api/puzzle/daily"),
        json={
            "game": {"pgn": "e4 e5"},
            "puzzle": {"id": "pzzle", "rating": 1500, "themes": ["fork"],
                       "initialPly": 2, "solution": ["f1c4"]},
        },
    )

    result = await drills.recommend_drills(
        "testuser", source="lichess", max_games=10, depth=8, num_drills=5
    )

    assert result["games_analyzed"] == 2
    assert result["drills"], "expected at least one drill"
    for d in result["drills"]:
        assert d["type"] == "own_blunder"
        assert d["fen"]
        assert d["side_to_move"] in ("white", "black")
        assert d["answer_uci"] or d["answer_san"]
        assert d["prompt_ko"]
        assert d["board_ascii"]
        assert d["lichess_url"].startswith("https://lichess.org/analysis/")
    assert result["bonus_puzzle"] is not None
    assert result["bonus_puzzle"]["fen"]
    assert result["focus_areas"]


@pytest.mark.engine
async def test_recommend_drills_survives_puzzle_failure(
    httpx_mock, lichess_game, lichess_ndjson, scholar_pgn
):
    games = [
        lichess_game(scholar_pgn, user="testuser", user_color="black", winner="white"),
    ]
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"),
        text=lichess_ndjson(games),
    )
    # Daily puzzle endpoint errors out -> bonus should be None, call still works.
    httpx_mock.add_response(
        url=re.compile(r".*/api/puzzle/daily"), status_code=503
    )
    result = await drills.recommend_drills(
        "testuser", source="lichess", max_games=5, depth=8, num_drills=3
    )
    assert result["drills"]
    assert result["bonus_puzzle"] is None
