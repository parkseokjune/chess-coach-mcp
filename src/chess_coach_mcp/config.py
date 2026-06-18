"""Configuration and Stockfish binary discovery.

All tunables live here so the engine, analysis and server share one source of
truth. Thresholds use Lichess' win-percentage model (see :mod:`engine`).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

# Common install locations checked after $STOCKFISH_PATH and $PATH.
_COMMON_STOCKFISH_PATHS = (
    "/opt/homebrew/bin/stockfish",  # macOS Apple-silicon Homebrew
    "/usr/local/bin/stockfish",  # macOS Intel Homebrew / manual
    "/usr/bin/stockfish",  # Debian/Ubuntu apt
    "/usr/games/stockfish",  # Debian/Ubuntu alt
    "/opt/local/bin/stockfish",  # MacPorts
)


def find_stockfish(explicit: Optional[str] = None) -> Optional[str]:
    """Return the first usable Stockfish executable, or ``None``.

    Resolution order: ``explicit`` arg -> ``$STOCKFISH_PATH`` -> ``PATH`` ->
    well-known install locations.
    """
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("STOCKFISH_PATH")
    if env:
        candidates.append(env)
    on_path = shutil.which("stockfish")
    if on_path:
        candidates.append(on_path)
    candidates.extend(_COMMON_STOCKFISH_PATHS)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime settings, overridable via environment variables."""

    # Engine process configuration.
    engine_threads: int = 1
    engine_hash_mb: int = 128

    # Default search limits. Depth keeps analysis deterministic-ish and fast.
    default_position_depth: int = 16
    default_game_depth: int = 14
    default_diagnose_depth: int = 12

    # Win-percentage drop thresholds for move classification (0-100 scale).
    inaccuracy_winpct: float = 5.0
    mistake_winpct: float = 10.0
    blunder_winpct: float = 20.0

    # Centipawn loss is capped before averaging so a single disaster does not
    # swamp the ACPL metric.
    cp_loss_cap: int = 1000

    # Mate scores are mapped to this many centipawns for the win-% model.
    mate_score: int = 10000

    # HTTP client configuration for game sources.
    http_timeout: float = 30.0
    user_agent: str = "chess-coach-mcp/0.1 (+https://github.com/parkseokjune/chess-coach-mcp)"

    # Safety caps so a single tool call cannot run unbounded.
    max_games_cap: int = 50
    max_plies_cap: int = 400


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        engine_threads=_int_env("CHESS_COACH_ENGINE_THREADS", 1),
        engine_hash_mb=_int_env("CHESS_COACH_ENGINE_HASH_MB", 128),
        default_position_depth=_int_env("CHESS_COACH_POSITION_DEPTH", 16),
        default_game_depth=_int_env("CHESS_COACH_GAME_DEPTH", 14),
        default_diagnose_depth=_int_env("CHESS_COACH_DIAGNOSE_DEPTH", 12),
    )
