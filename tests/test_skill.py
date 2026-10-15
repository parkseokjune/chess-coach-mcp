"""Keep the Agent Skill and Claude Code plugin packaging in sync with the code.

The skill (skills/chess-coach/SKILL.md) tells the host model when and how to
call each tool, and the plugin manifest ships it next to the server. These
tests fail when a tool is added without documenting it, or when the package,
plugin and skill versions drift apart.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import chess_coach_mcp
from chess_coach_mcp import server

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "chess-coach"
PLUGIN_DIR = ROOT / ".claude-plugin"


def _frontmatter(text: str) -> dict:
    """Parse the flat `key: value` frontmatter (plus one nested `metadata` map)."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with a --- frontmatter block"
    fields: dict = {}
    parent = None
    for line in match.group(1).splitlines():
        key, _, value = line.strip().partition(":")
        value = value.strip().strip('"')
        if line.startswith("  ") and parent:
            fields[parent][key] = value
        elif value:
            fields[key] = value
            parent = None
        else:
            fields[key] = {}
            parent = key
    return fields


def _skill() -> tuple[dict, str]:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    return _frontmatter(text), text


def _pyproject_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_skill_frontmatter_follows_agent_skills_spec():
    meta, _ = _skill()
    assert meta["name"] == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"])
    assert len(meta["name"]) <= 64
    assert 0 < len(meta["description"]) <= 1024
    assert 0 < len(meta["compatibility"]) <= 500


async def test_skill_documents_every_tool():
    _, text = _skill()
    tools = await server.mcp.list_tools()
    missing = [t.name for t in tools if not re.search(rf"`{t.name}\b", text)]
    assert not missing, f"SKILL.md does not mention: {missing}"


def test_versions_in_sync():
    plugin = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
    meta, _ = _skill()
    version = _pyproject_version()
    assert chess_coach_mcp.__version__ == version
    assert plugin["version"] == version
    assert meta["metadata"]["version"] == version


def test_marketplace_lists_the_plugin():
    plugin = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((PLUGIN_DIR / "marketplace.json").read_text(encoding="utf-8"))
    entries = {p["name"]: p for p in market["plugins"]}
    assert plugin["name"] in entries
    assert entries[plugin["name"]]["source"] == "./"
    assert "chess-coach" in plugin["mcpServers"]
