"""Tests for cross-game weakness diagnosis (mocked HTTP + real engine)."""

from __future__ import annotations

import re

import pytest

from chess_coach_mcp import diagnose, models


@pytest.mark.engine
async def test_diagnose_aggregates_two_games(
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

    result = await diagnose.diagnose_weaknesses(
        "testuser", source="lichess", max_games=10, depth=8
    )

    assert result["games_analyzed"] == 2
    assert result["overall"]["user_moves"] > 0
    assert result["overall"][models.BLUNDER] >= 1
    assert result["by_phase"]
    assert result["top_weaknesses"], "expected at least one weakness"
    # Both miniatures involve allowing a mate.
    spot_names = {s["motif"] for s in result["motif_blind_spots"]}
    assert models.MOTIF_ALLOWED_MATE in spot_names
    # Example blunders carry FENs (used by drills) and a game URL.
    assert result["example_blunders"]
    assert result["example_blunders"][0]["fen_before"]
    assert result["example_blunders"][0]["game_url"]


@pytest.mark.engine
async def test_diagnose_handles_no_games(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://lichess\.org/api/games/user/.*"), text=""
    )
    result = await diagnose.diagnose_weaknesses("nobody", source="lichess", depth=8)
    assert result["games_analyzed"] == 0
    assert result["overall"]["user_moves"] == 0
    assert any("No analysable games" in n for n in result["notes"])
