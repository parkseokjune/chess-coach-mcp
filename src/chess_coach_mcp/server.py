"""FastMCP server exposing the chess-coach toolset.

Design principle (the "hybrid coach"): these tools return engine-*grounded*
facts — evaluations, classifications, motifs, aggregated weaknesses. The MCP
host model turns those facts into natural-language (Korean) coaching. The tools
never invent chess judgements; Stockfish does the judging.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import analysis
from .config import find_stockfish, get_settings
from .diagnose import diagnose_weaknesses as _diagnose
from .drills import recommend_drills as _recommend_drills
from .engine import EngineError, StockfishEngine
from .sources import SourceError, fetch_games

INSTRUCTIONS = """\
Chess coaching tools backed by a local Stockfish engine and the Lichess /
Chess.com public APIs.

Use them like this:
1. fetch_recent_games(username) to see what someone has been playing.
2. analyze_game(pgn) for a single-game review, or diagnose_weaknesses(username)
   to find recurring weaknesses across many games.
3. recommend_drills(username) to get practice positions from the user's own
   mistakes.
4. analyze_position(fen) to explain a specific position.

Every tool returns structured, engine-grounded facts (centipawns, win%, move
classifications, tactical motifs). YOU produce the coaching prose. When the user
writes in Korean, coach in Korean — each fact ships with a *_ko label to help.
Always explain the 'why' behind the engine's preferred move; do not just repeat
the evaluation number.
"""

mcp = FastMCP("chess-coach", instructions=INSTRUCTIONS)


def _error(exc: Exception) -> dict:
    return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
def engine_status() -> dict:
    """Report whether the local Stockfish engine is available and its version.

    Call this first if other tools fail with an engine error.
    """
    path = find_stockfish()
    if not path:
        return {
            "available": False,
            "hint": "Install Stockfish (`brew install stockfish` or "
            "`apt install stockfish`) or set STOCKFISH_PATH.",
        }
    try:
        eng = StockfishEngine.get()
        name = eng._engine.id.get("name", "Stockfish")
        return {"available": True, "path": path, "engine": name}
    except EngineError as exc:
        return {"available": False, "path": path, **_error(exc)}


@mcp.tool()
async def analyze_position(fen: str, depth: int = 16, multipv: int = 3) -> dict:
    """Evaluate a single position (FEN) and return the top engine lines.

    Returns evaluation in centipawns and win%, the best lines in SAN, material
    balance, and simple tactical flags (fork threats, pins). Use this to explain
    *why* a move is best in a specific position.
    """
    try:
        return await asyncio.to_thread(
            analysis.analyze_position, fen, depth=depth, multipv=multipv
        )
    except (EngineError, ValueError) as exc:
        return _error(exc)


@mcp.tool()
async def analyze_game(
    pgn: str,
    depth: int = 14,
    user_color: Optional[str] = None,
    max_plies: int = 200,
) -> dict:
    """Analyse a full game from PGN: per-move classification + motifs + summary.

    Each move gets a classification (best/good/inaccuracy/mistake/blunder with
    Korean labels), win% before/after, centipawn loss, the engine's preferred
    move, and tactical-motif tags. The summary gives per-side accuracy/ACPL,
    per-phase breakdown, and the worst moments (with FENs for drilling).

    Set user_color to 'white' or 'black' to focus the worst-moment and motif
    reporting on one player.
    """
    try:
        return await asyncio.to_thread(
            analysis.analyze_game,
            pgn,
            depth=depth,
            user_color=user_color,
            max_plies=max_plies,
        )
    except (EngineError, ValueError) as exc:
        return _error(exc)


@mcp.tool()
async def fetch_recent_games(
    username: str,
    source: str = "lichess",
    max_games: int = 10,
    speed: Optional[str] = None,
) -> dict:
    """Fetch a player's recent games from Lichess or Chess.com (public data).

    source: 'lichess' or 'chesscom'. speed (optional) filters by
    bullet/blitz/rapid/classical. Returns normalised game records including PGN,
    players, ratings, result and opening. No analysis is run here.
    """
    try:
        records = await fetch_games(
            username, source=source, max_games=max_games, speed=speed
        )
        return {
            "username": username,
            "source": source,
            "count": len(records),
            "games": [r.to_dict() for r in records],
        }
    except SourceError as exc:
        return _error(exc)


@mcp.tool()
async def diagnose_weaknesses(
    username: str,
    source: str = "lichess",
    max_games: int = 15,
    depth: int = 12,
    speed: Optional[str] = None,
) -> dict:
    """Diagnose a player's recurring weaknesses across their recent games.

    Fetches recent games, analyses each from the player's perspective, and
    aggregates: overall accuracy/ACPL, per-phase (opening/middlegame/endgame)
    breakdown, recurring tactical blind spots (with example positions), leaky
    openings, a time-trouble proxy, and a ranked list of top weaknesses with
    example FENs. This is the core 'coach' tool — heavier (runs the engine over
    many games), so keep max_games modest for fast turnaround.
    """
    try:
        return await _diagnose(
            username, source=source, max_games=max_games, depth=depth, speed=speed
        )
    except (EngineError, SourceError) as exc:
        return _error(exc)


@mcp.tool()
async def recommend_drills(
    username: str,
    source: str = "lichess",
    max_games: int = 15,
    depth: int = 12,
    num_drills: int = 10,
    include_daily_puzzle: bool = True,
) -> dict:
    """Build a personalised drill set from the player's own mistakes.

    Runs diagnose_weaknesses, then returns re-solvable drill positions taken
    from the player's actual blunders (FEN, side to move, the engine's preferred
    move as the answer), ordered to target their top weaknesses, plus an
    optional Lichess daily puzzle as a warm-up.
    """
    try:
        return await _recommend_drills(
            username,
            source=source,
            max_games=max_games,
            depth=depth,
            num_drills=num_drills,
            include_daily_puzzle=include_daily_puzzle,
        )
    except (EngineError, SourceError) as exc:
        return _error(exc)


def main() -> None:
    """Console-script entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
