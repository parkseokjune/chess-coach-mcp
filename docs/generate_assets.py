"""Generate README visuals from REAL engine analysis (dogfooding the package).

Outputs (committed under docs/):
  - demo.gif            animated coaching demo (blunder -> engine's move -> pattern)
  - weakness_report.png the weakness "heatmap" produced by diagnose_weaknesses
  - board_example.png   a static annotated drill board

Run:
  uv run --with matplotlib --with pillow python docs/generate_assets.py

Requires a local Stockfish binary (same as the package).
"""

from __future__ import annotations

import os

import chess
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import colors, font_manager, patheffects  # noqa: E402
from matplotlib.animation import FuncAnimation, PillowWriter  # noqa: E402

from chess_coach_mcp.analysis import analyze_position  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

LIGHT, DARK = "#eadfc8", "#b07b53"
ACCENT_BAD, ACCENT_GOOD = "#d1495b", "#2a9d8f"
FILLED = {
    chess.PAWN: "♟",
    chess.KNIGHT: "♞",
    chess.BISHOP: "♝",
    chess.ROOK: "♜",
    chess.QUEEN: "♛",
    chess.KING: "♚",
}

# Try to find a Korean-capable font so captions can be bilingual.
_KO_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/AppleGothic.ttf",
    "/System/Library/Fonts/STHeiti Light.ttc",
]


def _ko_font(size: int):
    for path in _KO_CANDIDATES:
        if os.path.exists(path):
            return font_manager.FontProperties(fname=path, size=size)
    return font_manager.FontProperties(size=size)  # fallback (may not show Hangul)


def draw_board(ax, board, arrows=()):
    ax.clear()
    ax.set_xlim(0, 8)
    ax.set_ylim(0, 8)
    ax.set_aspect("equal")
    ax.axis("off")
    for r in range(8):
        for f in range(8):
            color = LIGHT if (r + f) % 2 else DARK
            ax.add_patch(plt.Rectangle((f, r), 1, 1, color=color, zorder=0))
    for sq, piece in board.piece_map().items():
        f, r = chess.square_file(sq), chess.square_rank(sq)
        fill = "#fbfbf8" if piece.color == chess.WHITE else "#222222"
        edge = "#222222" if piece.color == chess.WHITE else "#fbfbf8"
        t = ax.text(
            f + 0.5, r + 0.5, FILLED[piece.piece_type],
            fontsize=27, ha="center", va="center", color=fill, zorder=2,
        )
        t.set_path_effects([patheffects.withStroke(linewidth=1.4, foreground=edge)])
    for mv, color in arrows:
        f0, r0 = chess.square_file(mv.from_square), chess.square_rank(mv.from_square)
        f1, r1 = chess.square_file(mv.to_square), chess.square_rank(mv.to_square)
        ax.annotate(
            "", xy=(f1 + 0.5, r1 + 0.5), xytext=(f0 + 0.5, r0 + 0.5),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=4.5,
                            mutation_scale=26, alpha=0.9, shrinkA=10, shrinkB=10),
            zorder=3,
        )


# Real position: 1.e4 e5 2.Bc4 Nc6 3.Qh5 — Black to move (the Scholar's-mate trap).
DEMO_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
BLUNDER_UCI = "g8f6"  # ...Nf6?? allows Qxf7#


def _eval_demo():
    """Run the package's own analysis to label the demo honestly."""
    board = chess.Board(DEMO_FEN)
    before = analyze_position(DEMO_FEN, depth=16, multipv=1)
    best_uci = before["best_line"]["move_uci"]
    best_san = before["best_line"]["move_san"]
    win_before = before["win_pct_side_to_move"]

    after = board.copy()
    after.push(chess.Move.from_uci(BLUNDER_UCI))
    blunder_san = board.san(chess.Move.from_uci(BLUNDER_UCI))
    after_eval = analyze_position(after.fen(), depth=16, multipv=1)
    # after_eval is from White's POV; Black's win% is 100 - that.
    win_after_black = round(100 - after_eval["win_pct_side_to_move"], 1)
    return {
        "board": board,
        "best_uci": best_uci,
        "best_san": best_san,
        "blunder_san": blunder_san,
        "win_before": win_before,
        "win_after": win_after_black,
    }


def make_gif(info):
    board = info["board"]
    blunder = chess.Move.from_uci(BLUNDER_UCI)
    best = chess.Move.from_uci(info["best_uci"])

    scenes = [
        {
            "arrows": [(blunder, ACCENT_BAD)],
            "title": f"You played ...{info['blunder_san']}??",
            "sub": f"win% {info['win_before']:.0f} → {info['win_after']:.0f}  (a winning game, thrown away)",
            "ko": f"실수: ...{info['blunder_san']} — 이기던 판을 내줬어요",
            "color": ACCENT_BAD,
        },
        {
            "arrows": [(blunder, "#caa"), (best, ACCENT_GOOD)],
            "title": f"Engine prefers {info['best_san']}",
            "sub": "Stockfish says what; the coach explains why (defends f7).",
            "ko": f"엔진 추천: {info['best_san']} — f7을 지키세요",
            "color": ACCENT_GOOD,
        },
        {
            "arrows": [],
            "title": "Your recurring pattern: missed f7 / back-rank threats",
            "sub": "diagnose_weaknesses finds it across your games; drills fix it.",
            "ko": "반복되는 약점을 진단하고 맞춤 드릴로 연습",
            "color": "#264653",
        },
    ]

    fig = plt.figure(figsize=(5.4, 6.0), dpi=120)
    fig.patch.set_facecolor("#fcfbf7")
    ax = fig.add_axes([0.04, 0.20, 0.92, 0.74])  # board
    ax_t = fig.add_axes([0.0, 0.0, 1.0, 0.18])
    ax_t.axis("off")

    HOLD = 4  # frames per scene
    frame_to_scene = [i for i in range(len(scenes)) for _ in range(HOLD)]

    def update(frame):
        scene = scenes[frame_to_scene[frame]]
        draw_board(ax, board, scene["arrows"])
        ax.set_title("chess-coach-mcp", fontsize=11, color="#6b7280", pad=6)
        ax_t.clear()
        ax_t.axis("off")
        ax_t.add_patch(plt.Rectangle((0.03, 0.62), 0.02, 0.30, color=scene["color"],
                                     transform=ax_t.transAxes, clip_on=False))
        ax_t.text(0.08, 0.74, scene["title"], transform=ax_t.transAxes,
                  fontsize=12.5, fontweight="bold", color="#1f2937", va="center")
        ax_t.text(0.08, 0.46, scene["sub"], transform=ax_t.transAxes,
                  fontsize=9.5, color="#4b5563", va="center")
        ax_t.text(0.08, 0.18, scene["ko"], transform=ax_t.transAxes,
                  fontproperties=_ko_font(10), color="#6b7280", va="center")
        return []

    anim = FuncAnimation(fig, update, frames=len(frame_to_scene), interval=500)
    out = os.path.join(HERE, "demo.gif")
    anim.save(out, writer=PillowWriter(fps=2))
    plt.close(fig)
    print("wrote", out)


def make_board_png(info):
    fig = plt.figure(figsize=(4.6, 4.9), dpi=130)
    fig.patch.set_facecolor("#fcfbf7")
    ax = fig.add_axes([0.04, 0.13, 0.92, 0.83])
    draw_board(ax, info["board"], [
        (chess.Move.from_uci(BLUNDER_UCI), ACCENT_BAD),
        (chess.Move.from_uci(info["best_uci"]), ACCENT_GOOD),
    ])
    fig.text(0.5, 0.075, f"red = your move (...{info['blunder_san']})   "
                         f"green = engine ({info['best_san']})",
             ha="center", fontsize=9.5, color="#374151")
    fig.text(0.5, 0.025, "a drill rebuilt from your own blunder",
             ha="center", fontproperties=_ko_font(9), color="#6b7280")
    out = os.path.join(HERE, "board_example.png")
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", out)


def make_heatmap():
    # Representative EXAMPLE report (not a real person's data).
    accuracy = 76.4
    phases = [("Opening", 24), ("Middlegame", 41), ("Endgame", 73)]  # ACPL
    motifs = [
        ("Hanging piece", 9), ("Missed tactic", 6),
        ("Back-rank", 4), ("Fork", 3), ("Pin", 2),
    ]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(10, 3.9), dpi=130, gridspec_kw={"width_ratios": [1.25, 1]}
    )
    fig.patch.set_facecolor("#fcfbf7")
    fig.suptitle(
        f"diagnose_weaknesses — example report   (overall accuracy {accuracy}%)",
        fontsize=13, fontweight="bold", color="#1f2937", y=1.02,
    )

    # Blind-spots: horizontal bars colored as a severity heatmap.
    cmap = matplotlib.colormaps["YlOrRd"]
    labels = [m[0] for m in motifs][::-1]
    counts = [m[1] for m in motifs][::-1]
    norm = colors.Normalize(0, max(counts) * 1.15)
    ax1.barh(labels, counts, color=[cmap(norm(c)) for c in counts], edgecolor="#00000022")
    for i, c in enumerate(counts):
        ax1.text(c + 0.12, i, str(c), va="center", fontsize=10, color="#374151")
    ax1.set_title("Recurring tactical blind spots", fontsize=11, color="#374151")
    ax1.set_xlabel("times seen across recent games", fontsize=9, color="#6b7280")
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    # Per-phase ACPL bars colored by severity.
    pnames = [p[0] for p in phases]
    pvals = [p[1] for p in phases]
    pnorm = colors.Normalize(0, max(pvals) * 1.15)
    bars = ax2.bar(pnames, pvals, color=[cmap(pnorm(v)) for v in pvals], edgecolor="#00000022")
    for b, v in zip(bars, pvals):
        ax2.text(b.get_x() + b.get_width() / 2, v + 1.2, str(v), ha="center",
                 fontsize=10, color="#374151")
    ax2.set_title("Avg centipawn loss by phase", fontsize=11, color="#374151")
    ax2.set_ylabel("ACPL (lower is better)", fontsize=9, color="#6b7280")
    ax2.set_ylim(0, max(pvals) * 1.25)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)

    fig.text(0.5, -0.04,
             "endgames + hanging pieces are the weak spots → recommend_drills targets them first",
             ha="center", fontsize=9.5, color="#6b7280")
    out = os.path.join(HERE, "weakness_report.png")
    fig.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", out)


def main():
    info = _eval_demo()
    print(f"demo: blunder ...{info['blunder_san']} (win% {info['win_before']:.0f}->"
          f"{info['win_after']:.0f}); engine best {info['best_san']}")
    make_gif(info)
    make_board_png(info)
    make_heatmap()


if __name__ == "__main__":
    main()
