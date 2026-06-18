"""Game- and position-level analysis built on the engine + motif modules.

The pipeline evaluates every position in a game exactly once, then derives each
move's classification from the win% before the move and the win% after it
(reusing the next position's evaluation, negated). Motifs label the mistakes.
"""

from __future__ import annotations

import io
from typing import List, Optional

import chess
import chess.pgn

from . import models, motifs
from .config import get_settings
from .engine import Evaluation, StockfishEngine, move_accuracy, win_percent
from .motifs import PIECE_VALUE


def detect_phase(board: chess.Board) -> str:
    """Heuristic game-phase label for a position."""
    non_pawn_material = sum(
        PIECE_VALUE[p.piece_type]
        for p in board.piece_map().values()
        if p.piece_type not in (chess.KING, chess.PAWN)
    )
    if non_pawn_material <= 20:
        return models.PHASE_ENDGAME
    if board.fullmove_number <= 12:
        return models.PHASE_OPENING
    return models.PHASE_MIDDLEGAME


def _classify(win_drop: float, is_best: bool) -> str:
    s = get_settings()
    if is_best:
        return models.BEST
    if win_drop >= s.blunder_winpct:
        return models.BLUNDER
    if win_drop >= s.mistake_winpct:
        return models.MISTAKE
    if win_drop >= s.inaccuracy_winpct:
        return models.INACCURACY
    return models.GOOD


def _empty_side_stats() -> dict:
    return {
        "moves": 0,
        "acpl": 0.0,
        "accuracy": 0.0,
        models.BEST: 0,
        models.GOOD: 0,
        models.INACCURACY: 0,
        models.MISTAKE: 0,
        models.BLUNDER: 0,
        "_cp_loss_sum": 0,
        "_acc_sum": 0.0,
    }


def _finalize_side_stats(stats: dict) -> dict:
    n = stats["moves"]
    stats["acpl"] = round(stats.pop("_cp_loss_sum") / n, 1) if n else 0.0
    stats["accuracy"] = round(stats.pop("_acc_sum") / n, 1) if n else 0.0
    return stats


def analyze_game(
    pgn: str,
    *,
    depth: Optional[int] = None,
    movetime: Optional[float] = None,
    user_color: Optional[str] = None,
    max_plies: Optional[int] = None,
    worst_n: int = 6,
    engine: Optional[StockfishEngine] = None,
) -> dict:
    """Analyse a full game from PGN text.

    ``user_color`` ('white'/'black') focuses worst-moment and motif reporting on
    one player; if omitted, both sides are pooled.
    """
    settings = get_settings()
    if depth is None and movetime is None:
        depth = settings.default_game_depth

    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        raise ValueError("Could not parse PGN: no game found.")

    eng = engine or StockfishEngine.get()

    start_board = game.board()
    moves = list(game.mainline_moves())
    # Clamp to [0, max_plies_cap] so a negative value can't slice from the end
    # and a huge value can't bypass the safety cap.
    if max_plies is not None:
        cap = min(max(0, max_plies), settings.max_plies_cap)
    else:
        cap = settings.max_plies_cap
    truncated = len(moves) > cap
    if truncated:
        moves = moves[:cap]

    # Build the position list: boards[i] is the position *before* move i;
    # boards[-1] is the final position.
    boards: List[chess.Board] = [start_board.copy()]
    cursor = start_board.copy()
    for mv in moves:
        cursor.push(mv)
        boards.append(cursor.copy())

    # Evaluate every position once (terminal positions get a None sentinel).
    evals: List[Optional[Evaluation]] = []
    for b in boards:
        if b.is_game_over():
            evals.append(None)
        else:
            evals.append(eng.evaluate(b, depth=depth, movetime=movetime, multipv=1))

    move_reports: List[dict] = []
    side_stats = {"white": _empty_side_stats(), "black": _empty_side_stats()}

    for i, mv in enumerate(moves):
        b_before = boards[i]
        b_after = boards[i + 1]
        mover = b_before.turn
        side = "white" if mover == chess.WHITE else "black"
        ev_before = evals[i]
        assert ev_before is not None  # a position with a move is never terminal

        eb_cp = ev_before.cp
        eb_mate = ev_before.mate
        win_before = win_percent(eb_cp)
        best_uci = ev_before.best_move

        if b_after.is_game_over():
            if b_after.is_checkmate():
                ea_cp = settings.mate_score
                ea_mate = 0
                win_after = 100.0
            else:  # stalemate / draw by rule
                ea_cp = 0
                ea_mate = None
                win_after = 50.0
            opp_mate = None
        else:
            ev_after = evals[i + 1]
            assert ev_after is not None
            ea_cp = -ev_after.cp  # convert opponent POV -> mover POV
            ea_mate = -ev_after.mate if ev_after.mate is not None else None
            win_after = win_percent(ea_cp)
            opp_mate = ev_after.mate

        played_uci = mv.uci()
        is_best = best_uci == played_uci
        win_drop = win_before - win_after
        cls = _classify(win_drop, is_best)

        cp_loss = max(0, eb_cp - ea_cp)
        cp_loss = min(cp_loss, settings.cp_loss_cap)

        # "Missed" mate = had a forced mate, then neither delivered it nor kept
        # one. Delivering checkmate must NOT count as missing it.
        delivered_mate = b_after.is_checkmate()
        missed_mate = (
            (eb_mate is not None and eb_mate > 0)
            and not delivered_mate
            and not (ea_mate is not None and ea_mate > 0)
        )
        allowed_mate = opp_mate is not None and opp_mate > 0

        tags = motifs.tags_for_move(
            b_before,
            b_after,
            mover=mover,
            is_error=cls in models.ERROR_CLASSES,
            missed_mate=missed_mate,
            allowed_mate=allowed_mate,
        )

        best_san = None
        if best_uci:
            try:
                best_san = b_before.san(chess.Move.from_uci(best_uci))
            except (ValueError, AssertionError):
                best_san = None

        phase = detect_phase(b_before)
        accuracy = move_accuracy(win_before, win_after)

        move_reports.append(
            {
                "ply": i + 1,
                "move_number": b_before.fullmove_number,
                "side": side,
                "san": b_before.san(mv),
                "uci": played_uci,
                "classification": cls,
                "classification_ko": models.CLASS_KO[cls],
                "cp_before": eb_cp,
                "cp_after": ea_cp,
                "win_before": round(win_before, 1),
                "win_after": round(win_after, 1),
                "win_drop": round(max(0.0, win_drop), 1),
                "cp_loss": cp_loss,
                "accuracy": round(accuracy, 1),
                "best_move_uci": best_uci,
                "best_move_san": best_san,
                "phase": phase,
                "phase_ko": models.PHASE_KO[phase],
                "fen_before": b_before.fen(),
                "motifs": tags,
            }
        )

        st = side_stats[side]
        st["moves"] += 1
        st[cls] += 1
        st["_cp_loss_sum"] += cp_loss
        st["_acc_sum"] += accuracy

    # --- summaries ---------------------------------------------------------
    focus_sides = [user_color] if user_color in ("white", "black") else ["white", "black"]
    by_phase: dict = {}
    motif_counts: dict = {}
    worst: List[dict] = []

    for rep in move_reports:
        if rep["side"] not in focus_sides:
            continue
        ph = rep["phase"]
        bucket = by_phase.setdefault(
            ph,
            {"phase_ko": models.PHASE_KO[ph], "moves": 0, "_cp": 0, "errors": 0},
        )
        bucket["moves"] += 1
        bucket["_cp"] += rep["cp_loss"]
        if rep["classification"] in models.ERROR_CLASSES:
            bucket["errors"] += 1
        for t in rep["motifs"]:
            motif_counts[t["motif"]] = motif_counts.get(t["motif"], 0) + 1
        if rep["classification"] in (models.MISTAKE, models.BLUNDER):
            worst.append(rep)

    for ph, bucket in by_phase.items():
        n = bucket["moves"]
        bucket["acpl"] = round(bucket.pop("_cp") / n, 1) if n else 0.0

    worst.sort(key=lambda r: r["win_drop"], reverse=True)
    worst_moments = [
        {
            "ply": r["ply"],
            "move_number": r["move_number"],
            "side": r["side"],
            "san": r["san"],
            "best_move_san": r["best_move_san"],
            "best_move_uci": r["best_move_uci"],
            "classification": r["classification"],
            "classification_ko": r["classification_ko"],
            "win_drop": r["win_drop"],
            "phase": r["phase"],
            "motifs": r["motifs"],
            "fen_before": r["fen_before"],
        }
        for r in worst[:worst_n]
    ]

    headers = game.headers
    return {
        "source": "pgn",
        "white": headers.get("White", "?"),
        "black": headers.get("Black", "?"),
        "result": headers.get("Result", "*"),
        "opening": headers.get("Opening") or headers.get("ECO"),
        "user_color": user_color if user_color in ("white", "black") else None,
        "depth": depth,
        "movetime": movetime,
        "total_plies": len(moves),
        "truncated": truncated,
        "moves": move_reports,
        "summary": {
            "white": _finalize_side_stats(side_stats["white"]),
            "black": _finalize_side_stats(side_stats["black"]),
            "by_phase": by_phase,
        },
        "motif_counts": motif_counts,
        "worst_moments": worst_moments,
    }


def _material_count(board: chess.Board) -> dict:
    white = sum(
        PIECE_VALUE[p.piece_type]
        for p in board.piece_map().values()
        if p.color == chess.WHITE and p.piece_type != chess.KING
    )
    black = sum(
        PIECE_VALUE[p.piece_type]
        for p in board.piece_map().values()
        if p.color == chess.BLACK and p.piece_type != chess.KING
    )
    return {"white": white, "black": black, "balance": white - black}


def analyze_position(
    fen: str,
    *,
    depth: Optional[int] = None,
    multipv: int = 3,
    engine: Optional[StockfishEngine] = None,
) -> dict:
    """Evaluate a single FEN and return engine lines plus light positional facts.

    The MCP host turns these grounded facts into the 'why' explanation.
    """
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ValueError(f"Invalid FEN: {exc}") from exc

    if board.is_game_over():
        return {
            "fen": board.fen(),
            "game_over": True,
            "outcome": board.result(),
            "is_checkmate": board.is_checkmate(),
            "is_stalemate": board.is_stalemate(),
            "side_to_move": "white" if board.turn == chess.WHITE else "black",
        }

    settings = get_settings()
    if depth is None:
        depth = settings.default_position_depth
    eng = engine or StockfishEngine.get()
    ev = eng.evaluate(board, depth=depth, multipv=multipv)

    lines = []
    for ln in ev.lines:
        san_pv = []
        tmp = board.copy()
        for u in ln["pv"][:6]:
            try:
                m = chess.Move.from_uci(u)
                san_pv.append(tmp.san(m))
                tmp.push(m)
            except (ValueError, AssertionError):
                break
        lines.append(
            {
                "move_uci": ln["move"],
                "move_san": san_pv[0] if san_pv else None,
                "cp": ln["cp"],
                "mate": ln["mate"],
                "win_pct": round(win_percent(ln["cp"]), 1),
                "pv_san": san_pv,
            }
        )

    mover = "white" if board.turn == chess.WHITE else "black"
    return {
        "fen": board.fen(),
        "game_over": False,
        "side_to_move": mover,
        "depth": ev.depth or depth,
        "eval_cp": ev.cp,
        "eval_mate": ev.mate,
        "win_pct_side_to_move": round(ev.win_pct, 1),
        "material": _material_count(board),
        "in_check": board.is_check(),
        "best_line": lines[0] if lines else None,
        "lines": lines,
        "fork_threats": motifs.detect_fork(board, board.turn),
        "pins_against_opponent": motifs.detect_pins(board, board.turn),
    }
