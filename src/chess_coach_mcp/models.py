"""Shared data structures, constants and bilingual (EN/KO) labels.

The MCP host LLM produces the natural-language coaching, so every structured
value that might appear in coaching prose ships with a Korean label alongside
the English key. That is the core "hybrid" idea: the engine supplies grounded
facts, the model supplies the Korean explanation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# --- Move classifications --------------------------------------------------
BEST = "best"
GOOD = "good"
INACCURACY = "inaccuracy"
MISTAKE = "mistake"
BLUNDER = "blunder"

# Worst-to-best ordering is handy for "is this at least a mistake?" checks.
CLASS_SEVERITY = {BEST: 0, GOOD: 1, INACCURACY: 2, MISTAKE: 3, BLUNDER: 4}

CLASS_KO = {
    BEST: "최선수",
    GOOD: "좋은 수",
    INACCURACY: "부정확수",
    MISTAKE: "실수",
    BLUNDER: "대실수",
}

# Classifications that count as real errors for diagnosis purposes.
ERROR_CLASSES = (INACCURACY, MISTAKE, BLUNDER)

# --- Game phases -----------------------------------------------------------
PHASE_OPENING = "opening"
PHASE_MIDDLEGAME = "middlegame"
PHASE_ENDGAME = "endgame"

PHASE_KO = {
    PHASE_OPENING: "오프닝",
    PHASE_MIDDLEGAME: "미들게임",
    PHASE_ENDGAME: "엔드게임",
}

# --- Tactical motifs -------------------------------------------------------
MOTIF_HANGING = "hanging_piece"
MOTIF_FORK = "fork"
MOTIF_PIN = "pin"
MOTIF_BACK_RANK = "back_rank"
MOTIF_MISSED_MATE = "missed_mate"
MOTIF_ALLOWED_MATE = "allowed_mate"
MOTIF_MISSED_TACTIC = "missed_tactic"

MOTIF_KO = {
    MOTIF_HANGING: "무방비 기물(행잉)",
    MOTIF_FORK: "포크",
    MOTIF_PIN: "핀",
    MOTIF_BACK_RANK: "백랭크 약점",
    MOTIF_MISSED_MATE: "외통 기회 놓침",
    MOTIF_ALLOWED_MATE: "외통 허용",
    MOTIF_MISSED_TACTIC: "전술 기회 놓침",
}


def motif(name: str, **extra: Any) -> dict:
    """Build a motif dict with the bilingual label attached."""
    out = {"motif": name, "motif_ko": MOTIF_KO.get(name, name)}
    out.update(extra)
    return out


@dataclass
class GameRecord:
    """A single game normalised across Lichess / Chess.com sources."""

    source: str
    game_id: str
    url: str
    pgn: str
    white: str
    black: str
    result: str  # "1-0" | "0-1" | "1/2-1/2" | "*"
    white_rating: Optional[int] = None
    black_rating: Optional[int] = None
    time_control: Optional[str] = None  # e.g. "600+0"
    speed: Optional[str] = None  # bullet|blitz|rapid|classical|correspondence
    opening: Optional[str] = None
    eco: Optional[str] = None
    played_at: Optional[str] = None  # ISO-8601 if known

    def color_of(self, username: str) -> Optional[str]:
        """Return 'white'/'black' for ``username`` (case-insensitive) or None."""
        u = (username or "").strip().lower()
        if u and self.white.lower() == u:
            return "white"
        if u and self.black.lower() == u:
            return "black"
        return None

    def to_dict(self) -> dict:
        return asdict(self)
