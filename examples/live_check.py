"""Live end-to-end check against the real Lichess API + local Stockfish.

Run:  uv run python examples/live_check.py [lichess_username]

Hits the network. Not part of the pytest suite. Prints a concise report so you
can eyeball that fetching, single-game analysis and weakness diagnosis all work
on real data.
"""

from __future__ import annotations

import asyncio
import json
import sys

from chess_coach_mcp import analysis, diagnose, sources
from chess_coach_mcp.server import engine_status


async def main(username: str) -> None:
    print("== engine_status ==")
    print(json.dumps(engine_status(), ensure_ascii=False))

    print(f"\n== fetch_recent_games({username}, 3) ==")
    records = await sources.fetch_games(username, source="lichess", max_games=3)
    for r in records:
        print(f"  {r.game_id}  {r.white} vs {r.black}  {r.result}  [{r.speed}]  {r.opening}")
    if not records:
        print("  (no games returned)")
        return

    print("\n== analyze_game(first game, depth=12) ==")
    target = next((r for r in records if r.pgn), records[0])
    color = target.color_of(username) or "white"
    report = await asyncio.to_thread(
        analysis.analyze_game, target.pgn, depth=12, user_color=color
    )
    s = report["summary"][color]
    print(f"  {username} played {color}: accuracy={s['accuracy']}  ACPL={s['acpl']}  "
          f"blunders={s['blunder']} mistakes={s['mistake']} inacc={s['inaccuracy']}")
    print(f"  worst moments: {len(report['worst_moments'])}")
    for wm in report["worst_moments"][:3]:
        motif = ", ".join(m["motif"] for m in wm["motifs"]) or "-"
        print(f"    move {wm['move_number']} {wm['san']} ({wm['classification']}, "
              f"-{wm['win_drop']}% win) best={wm['best_move_san']} motifs=[{motif}]")

    print("\n== diagnose_weaknesses(depth=10, max_games=3) ==")
    diag = await diagnose.diagnose_weaknesses(
        username, source="lichess", max_games=3, depth=10
    )
    print(f"  games_analyzed={diag['games_analyzed']}  "
          f"overall accuracy={diag['overall']['accuracy']} ACPL={diag['overall']['acpl']}")
    print(f"  by_phase: " + ", ".join(
        f"{ph}: ACPL {d['acpl']} ({d['errors']} err)" for ph, d in diag["by_phase"].items()
    ))
    print("  top weaknesses:")
    for w in diag["top_weaknesses"]:
        print(f"    [{w['category']}] {w['theme']} ({w['theme_ko']}) — {w['detail']}")
    print(f"  example blunder FENs collected: {len(diag['example_blunders'])}")


if __name__ == "__main__":
    user = sys.argv[1] if len(sys.argv) > 1 else "DrNykterstein"
    asyncio.run(main(user))
