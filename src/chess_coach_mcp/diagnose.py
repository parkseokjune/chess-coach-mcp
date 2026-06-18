"""Cross-game weakness diagnosis.

Fetches a player's recent games, analyses each from that player's perspective,
and aggregates the per-game reports into phase weaknesses, recurring tactical
blind spots, leaky openings, and a ranked list of top weaknesses with concrete
example positions drawn from the player's own games. This is the feature that
turns "random puzzles" into "here is *your* recurring mistake".
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

import httpx

from . import models
from .analysis import analyze_game
from .config import get_settings
from .engine import StockfishEngine
from .sources import fetch_games

# How many example positions to keep per motif / weakness.
_MAX_EXAMPLES = 3


def _score_for(result: str, color: str) -> Optional[float]:
    if result == "1-0":
        return 1.0 if color == "white" else 0.0
    if result == "0-1":
        return 1.0 if color == "black" else 0.0
    if result == "1/2-1/2":
        return 0.5
    return None  # unknown / ongoing


async def diagnose_weaknesses(
    username: str,
    source: str = "lichess",
    max_games: int = 15,
    *,
    depth: Optional[int] = None,
    speed: Optional[str] = None,
    max_plies: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    settings = get_settings()
    if depth is None:
        depth = settings.default_diagnose_depth

    records = await fetch_games(
        username, source=source, max_games=max_games, speed=speed, client=client
    )

    # Ensure the engine is started before entering threads (clean error if not).
    # Bootstrapping spawns a subprocess + UCI handshake, so do it off the loop.
    eng = await asyncio.to_thread(StockfishEngine.get)

    overall = {
        "user_moves": 0,
        models.BEST: 0,
        models.GOOD: 0,
        models.INACCURACY: 0,
        models.MISTAKE: 0,
        models.BLUNDER: 0,
        "_cp_sum": 0.0,
        "_acc_sum": 0.0,
    }
    phase_agg: dict = {}
    motif_agg: dict = {}
    motif_examples: dict = {}
    openings: dict = {}
    example_blunders: List[dict] = []
    late_blunders = 0
    games_analyzed = 0
    notes: List[str] = []

    for rec in records:
        color = rec.color_of(username)
        if color is None:
            continue  # user isn't a named player in this game; skip
        if not rec.pgn:
            continue
        try:
            report = await asyncio.to_thread(
                analyze_game,
                rec.pgn,
                depth=depth,
                user_color=color,
                max_plies=max_plies,
                engine=eng,
            )
        except Exception as exc:  # one bad game shouldn't kill the batch
            notes.append(f"Skipped game {rec.game_id}: {exc}")
            continue

        games_analyzed += 1
        side = report["summary"][color]
        overall["user_moves"] += side["moves"]
        overall["_cp_sum"] += side["acpl"] * side["moves"]
        overall["_acc_sum"] += side["accuracy"] * side["moves"]
        for cls in models.CLASS_SEVERITY:
            overall[cls] += side.get(cls, 0)

        for ph, bucket in report["summary"]["by_phase"].items():
            agg = phase_agg.setdefault(
                ph, {"phase_ko": models.PHASE_KO[ph], "moves": 0, "_cp": 0.0, "errors": 0}
            )
            agg["moves"] += bucket["moves"]
            agg["_cp"] += bucket["acpl"] * bucket["moves"]
            agg["errors"] += bucket["errors"]

        for m, c in report["motif_counts"].items():
            motif_agg[m] = motif_agg.get(m, 0) + c

        # Late blunders (after move 30) counted over the FULL move list so the
        # numerator shares a population with total_blunders (which counts every
        # blunder, not just the capped worst_moments).
        for mv in report["moves"]:
            if (
                mv["side"] == color
                and mv["classification"] == models.BLUNDER
                and mv["move_number"] > 30
            ):
                late_blunders += 1

        # Openings, scored from the user's perspective.
        opening_name = rec.opening or rec.eco or "Unknown"
        key = (opening_name, color)
        op = openings.setdefault(
            key,
            {
                "opening": opening_name,
                "eco": rec.eco,
                "color": color,
                "games": 0,
                "_score_sum": 0.0,
                "_score_games": 0,
                "_cp": 0.0,
                "_moves": 0,
            },
        )
        op["games"] += 1
        op["_cp"] += side["acpl"] * side["moves"]
        op["_moves"] += side["moves"]
        sc = _score_for(rec.result, color)
        if sc is not None:
            op["_score_sum"] += sc
            op["_score_games"] += 1

        # Worst moments -> example blunders + per-motif examples.
        for wm in report["worst_moments"]:
            enriched = dict(wm)
            enriched["game_url"] = rec.url
            enriched["game_id"] = rec.game_id
            enriched["color"] = color
            example_blunders.append(enriched)
            for t in wm["motifs"]:
                bucket = motif_examples.setdefault(t["motif"], [])
                if len(bucket) < _MAX_EXAMPLES:
                    bucket.append(
                        {
                            "fen": wm["fen_before"],
                            "best_move_san": wm["best_move_san"],
                            "played_san": wm["san"],
                            "game_url": rec.url,
                        }
                    )

    # --- finalise aggregates ----------------------------------------------
    n_moves = overall["user_moves"]
    overall_out = {
        "user_moves": n_moves,
        "accuracy": round(overall.pop("_acc_sum") / n_moves, 1) if n_moves else 0.0,
        "acpl": round(overall.pop("_cp_sum") / n_moves, 1) if n_moves else 0.0,
        **{cls: overall[cls] for cls in models.CLASS_SEVERITY},
    }

    by_phase = {}
    for ph, agg in phase_agg.items():
        n = agg["moves"]
        by_phase[ph] = {
            "phase_ko": agg["phase_ko"],
            "moves": n,
            "acpl": round(agg["_cp"] / n, 1) if n else 0.0,
            "errors": agg["errors"],
            "error_rate": round(agg["errors"] / n, 3) if n else 0.0,
        }

    motif_blind_spots = [
        {
            "motif": m,
            "motif_ko": models.MOTIF_KO.get(m, m),
            "count": c,
            "examples": motif_examples.get(m, []),
        }
        for m, c in sorted(motif_agg.items(), key=lambda kv: kv[1], reverse=True)
    ]

    openings_out = []
    for op in openings.values():
        games = op["games"]
        openings_out.append(
            {
                "opening": op["opening"],
                "eco": op["eco"],
                "color": op["color"],
                "games": games,
                "score_pct": round(100 * op["_score_sum"] / op["_score_games"], 1)
                if op["_score_games"]
                else None,
                "acpl": round(op["_cp"] / op["_moves"], 1) if op["_moves"] else 0.0,
            }
        )
    # Worst openings: highest ACPL, prioritising those seen more than once.
    openings_out.sort(key=lambda o: (o["games"] >= 2, o["acpl"]), reverse=True)

    example_blunders.sort(key=lambda b: b["win_drop"], reverse=True)
    example_blunders = example_blunders[:12]

    total_blunders = overall_out[models.BLUNDER]
    time_trouble = {
        "late_blunders": late_blunders,
        "total_blunders": total_blunders,
        "late_blunder_rate": round(late_blunders / total_blunders, 2)
        if total_blunders
        else 0.0,
        "note": "Proxy only: counts blunders after move 30. Clock data is not "
        "analysed, so this approximates fatigue/time-trouble, not true clock usage.",
    }

    top_weaknesses = _synthesize_weaknesses(
        overall_out, by_phase, motif_blind_spots, openings_out, motif_examples
    )

    if games_analyzed == 0:
        notes.append(
            f"No analysable games found for '{username}' on {source}. Check the "
            "username and that the account has public games."
        )

    return {
        "username": username,
        "source": source,
        "speed": speed,
        "depth": depth,
        "games_requested": max_games,
        "games_analyzed": games_analyzed,
        "overall": overall_out,
        "by_phase": by_phase,
        "motif_blind_spots": motif_blind_spots,
        "openings": openings_out[:8],
        "time_trouble_proxy": time_trouble,
        "top_weaknesses": top_weaknesses,
        "example_blunders": example_blunders,
        "notes": notes,
    }


def _synthesize_weaknesses(
    overall: dict,
    by_phase: dict,
    motif_blind_spots: List[dict],
    openings: List[dict],
    motif_examples: dict,
) -> List[dict]:
    """Combine signals into a small ranked list of actionable weaknesses."""
    candidates: List[dict] = []

    # 1) Recurring tactical motifs (the strongest, most concrete signal).
    for spot in motif_blind_spots:
        if spot["count"] < 2:
            continue
        candidates.append(
            {
                "theme": spot["motif"],
                "theme_ko": spot["motif_ko"],
                "category": "tactic",
                "detail": f"Recurred {spot['count']} times across analysed games.",
                "severity": float(spot["count"]) * 2.0,
                "example_fens": [e["fen"] for e in spot["examples"]],
            }
        )

    # 2) Weakest phase, if it is clearly worse than the player's own average.
    if by_phase:
        worst_phase = max(by_phase.items(), key=lambda kv: kv[1]["acpl"])
        ph, data = worst_phase
        if data["acpl"] > overall["acpl"] * 1.15 and data["moves"] >= 5:
            candidates.append(
                {
                    "theme": f"{ph}_accuracy",
                    "theme_ko": f"{models.PHASE_KO[ph]} 정확도",
                    "category": "phase",
                    "detail": f"ACPL {data['acpl']} in the {ph} vs {overall['acpl']} "
                    f"overall ({data['errors']} errors).",
                    "severity": float(data["errors"]) + data["acpl"] / 50.0,
                    "example_fens": [],
                }
            )

    # 3) Leakiest repeated opening.
    repeated = [o for o in openings if o["games"] >= 2]
    if repeated:
        worst_open = max(repeated, key=lambda o: o["acpl"])
        candidates.append(
            {
                "theme": "opening_leak",
                "theme_ko": "오프닝 누수",
                "category": "opening",
                "detail": f"{worst_open['opening']} as {worst_open['color']}: "
                f"ACPL {worst_open['acpl']} over {worst_open['games']} games"
                + (
                    f", scoring {worst_open['score_pct']}%."
                    if worst_open["score_pct"] is not None
                    else "."
                ),
                "severity": worst_open["acpl"] / 40.0,
                "example_fens": [],
            }
        )

    candidates.sort(key=lambda c: c["severity"], reverse=True)
    for i, c in enumerate(candidates[:5], start=1):
        c["rank"] = i
    return candidates[:5]
