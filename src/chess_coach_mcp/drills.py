"""Turn diagnosed weaknesses into concrete, re-solvable drills.

The core drill source is the player's *own* blunder positions: there is no more
personalised exercise than re-playing the exact spot you went wrong, now
knowing the engine's preferred move. A Lichess daily puzzle is added as a
bonus warm-up when available.
"""

from __future__ import annotations

from typing import List, Optional

import httpx

from . import models
from .diagnose import diagnose_weaknesses
from .sources import fetch_daily_puzzle


def _side_to_move(fen: str) -> str:
    parts = fen.split()
    return "white" if len(parts) < 2 or parts[1] == "w" else "black"


def _theme_for(blunder: dict) -> tuple[str, str]:
    motifs = blunder.get("motifs") or []
    if motifs:
        m = motifs[0]
        return m["motif"], m.get("motif_ko", m["motif"])
    phase = blunder.get("phase", "")
    return phase, models.PHASE_KO.get(phase, phase)


def _drill_from_blunder(eb: dict) -> dict:
    stm = _side_to_move(eb["fen_before"])
    stm_ko = "백" if stm == "white" else "흑"
    theme, theme_ko = _theme_for(eb)
    return {
        "type": "own_blunder",
        "fen": eb["fen_before"],
        "side_to_move": stm,
        "theme": theme,
        "theme_ko": theme_ko,
        "prompt": f"{stm.capitalize()} to move. You went wrong here in a real "
        "game — find the move the engine prefers.",
        "prompt_ko": f"{stm_ko}의 차례입니다. 실제 대국에서 실수했던 자리예요. "
        "엔진이 추천하는 수를 찾아보세요.",
        "your_move_san": eb.get("san"),
        "answer_san": eb.get("best_move_san"),
        "answer_uci": eb.get("best_move_uci"),
        "win_drop": eb.get("win_drop"),
        "phase": eb.get("phase"),
        "game_url": eb.get("game_url"),
    }


async def recommend_drills(
    username: str,
    source: str = "lichess",
    max_games: int = 15,
    *,
    depth: Optional[int] = None,
    speed: Optional[str] = None,
    num_drills: int = 10,
    include_daily_puzzle: bool = True,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    diagnosis = await diagnose_weaknesses(
        username,
        source=source,
        max_games=max_games,
        depth=depth,
        speed=speed,
        client=client,
    )

    top_themes = [w["theme"] for w in diagnosis["top_weaknesses"]]
    blunders = diagnosis["example_blunders"]

    # Order drills so that positions illustrating a top weakness come first,
    # then the rest by severity (already win_drop-sorted).
    def priority(eb: dict) -> tuple:
        eb_motifs = {m["motif"] for m in (eb.get("motifs") or [])}
        matches_top = bool(eb_motifs.intersection(top_themes))
        return (matches_top, eb.get("win_drop", 0))

    ordered = sorted(blunders, key=priority, reverse=True)
    drills = [_drill_from_blunder(eb) for eb in ordered[: max(0, num_drills)]]

    bonus = None
    if include_daily_puzzle:
        try:
            puzzle = await fetch_daily_puzzle(client=client)
            solution = puzzle.get("solution") or []
            bonus = {
                "type": "lichess_daily_puzzle",
                "fen": puzzle["fen"],
                "side_to_move": puzzle["side_to_move"],
                "themes": puzzle.get("themes", []),
                "rating": puzzle.get("rating"),
                "prompt": f"{puzzle['side_to_move'].capitalize()} to move. "
                "Lichess daily puzzle — warm-up.",
                "prompt_ko": "오늘의 Lichess 퍼즐로 몸을 풀어보세요.",
                "answer_uci": solution[0] if solution else None,
                "url": puzzle.get("url"),
            }
        except Exception:
            bonus = None  # bonus only; never fail the whole call

    focus_areas = [
        {
            "rank": w.get("rank"),
            "theme": w["theme"],
            "theme_ko": w["theme_ko"],
            "category": w["category"],
            "detail": w["detail"],
        }
        for w in diagnosis["top_weaknesses"]
    ]

    return {
        "username": username,
        "source": source,
        "games_analyzed": diagnosis["games_analyzed"],
        "focus_areas": focus_areas,
        "num_drills": len(drills),
        "drills": drills,
        "bonus_puzzle": bonus,
        "coaching_hint": "Each own_blunder drill is a position from the player's "
        "own games. Quiz them on the position before revealing answer_san; relate "
        "the fix to the listed focus_areas.",
        "notes": diagnosis["notes"],
    }
