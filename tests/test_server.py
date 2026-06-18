"""Tests for the FastMCP server wiring."""

from __future__ import annotations

import pytest

from chess_coach_mcp import server

EXPECTED_TOOLS = {
    "engine_status",
    "render_board",
    "analyze_position",
    "analyze_game",
    "fetch_recent_games",
    "diagnose_weaknesses",
    "recommend_drills",
}


async def test_all_tools_registered():
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names


async def test_tools_have_descriptions():
    tools = await server.mcp.list_tools()
    for t in tools:
        assert t.description, f"tool {t.name} is missing a description"


def test_engine_status_shape():
    res = server.engine_status()
    assert "available" in res


async def test_analyze_position_tool_invalid_fen_returns_error():
    # The tool wraps errors into a structured dict rather than raising.
    res = await server.analyze_position("garbage", depth=6)
    assert "error" in res
