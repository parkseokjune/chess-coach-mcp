"""Heuristic tactical-motif detection.

These are deliberately conservative pattern detectors, not a tactics solver.
They exist to *label* engine-found mistakes with human-recognisable themes
("you hung a piece", "you missed a fork") so the coaching model and the
weakness diagnosis can group errors. They favour precision over recall and are
documented as heuristics throughout.

Where possible we use legal moves (which respect pins, checks and illegal king
captures) rather than raw attack geometry, so a depth-1 static-exchange check
is reasonably trustworthy.
"""

from __future__ import annotations

from typing import List

import chess

from . import models

PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

# A "valuable" target for fork purposes: knight value or above, plus the king.
_FORK_TARGET_MIN = 3


def winning_captures(board: chess.Board, min_gain: int = 1) -> List[dict]:
    """Captures available to the side to move that win >= ``min_gain`` material.

    Uses a depth-1 static exchange: victim value, minus the cheapest recapture
    if the destination square is defended. Relies on legal moves, so pinned
    attackers and illegal king captures are naturally excluded.
    """
    out: List[dict] = []
    them = not board.turn
    for mv in board.legal_moves:
        if not board.is_capture(mv):
            continue
        if board.is_en_passant(mv):
            victim_type = chess.PAWN
        else:
            victim_piece = board.piece_at(mv.to_square)
            if victim_piece is None:
                continue
            victim_type = victim_piece.piece_type
        attacker_type = board.piece_at(mv.from_square).piece_type
        victim_val = PIECE_VALUE[victim_type]

        board.push(mv)
        defended = bool(board.attackers(them, mv.to_square))
        board.pop()

        gain = victim_val - PIECE_VALUE[attacker_type] if defended else victim_val
        if gain >= min_gain:
            out.append(
                {
                    "move": mv.uci(),
                    "from": chess.square_name(mv.from_square),
                    "to": chess.square_name(mv.to_square),
                    "victim": chess.piece_name(victim_type),
                    "gain": gain,
                }
            )
    out.sort(key=lambda c: c["gain"], reverse=True)
    return out


def detect_fork(board: chess.Board, color: chess.Color) -> List[dict]:
    """Pieces of ``color`` that attack >= 2 valuable enemy targets at once.

    A target counts if it is the enemy king or worth >= a knight. To suppress
    false positives, the forking piece must not be worth more than every target
    it hits (a queen 'attacking' two minor pieces is not a fork).
    """
    forks: List[dict] = []
    enemy = not color
    for sq, piece in board.piece_map().items():
        if piece.color != color:
            continue
        # A piece absolutely pinned to its own king cannot deliver a real fork.
        if board.is_pinned(color, sq):
            continue
        forker_val = PIECE_VALUE[piece.piece_type]
        targets = []
        for target_sq in board.attacks(sq):
            tp = board.piece_at(target_sq)
            if tp is None or tp.color != enemy:
                continue
            is_king = tp.piece_type == chess.KING
            if is_king or PIECE_VALUE[tp.piece_type] >= _FORK_TARGET_MIN:
                targets.append((target_sq, tp))
        if len(targets) < 2:
            continue
        # Require at least one target the forker would happily win: the king, or
        # a piece worth at least as much as the forker.
        worthwhile = any(
            tp.piece_type == chess.KING or PIECE_VALUE[tp.piece_type] >= forker_val
            for _, tp in targets
        )
        if not worthwhile:
            continue
        forks.append(
            {
                "square": chess.square_name(sq),
                "piece": piece.symbol(),
                "targets": [chess.square_name(s) for s, _ in targets],
            }
        )
    return forks


def detect_pins(board: chess.Board, by_color: chess.Color) -> List[dict]:
    """Absolute pins (to the king) created by ``by_color`` against the enemy."""
    pins: List[dict] = []
    enemy = not by_color
    for sq, piece in board.piece_map().items():
        if piece.color != enemy or piece.piece_type == chess.KING:
            continue
        if board.is_pinned(enemy, sq):
            pins.append(
                {"square": chess.square_name(sq), "piece": piece.symbol()}
            )
    return pins


def back_rank_weakness(board: chess.Board, color: chess.Color) -> bool:
    """True if ``color``'s king is stuck on its back rank with no luft.

    Heuristic: king on its own back rank, every forward escape square blocked
    by a friendly piece, and the enemy still has a queen or rook to exploit it.
    """
    king_sq = board.king(color)
    if king_sq is None:
        return False
    back_rank = 0 if color == chess.WHITE else 7
    if chess.square_rank(king_sq) != back_rank:
        return False

    forward = 1 if color == chess.WHITE else -1
    file = chess.square_file(king_sq)
    escape_rank = back_rank + forward
    blocked = True
    for df in (-1, 0, 1):
        f = file + df
        if not 0 <= f <= 7:
            continue
        target = chess.square(f, escape_rank)
        occupant = board.piece_at(target)
        if occupant is None or occupant.color != color:
            blocked = False  # an empty/forward square gives the king luft
            break
    if not blocked:
        return False

    enemy = not color
    has_heavy = any(
        p.color == enemy and p.piece_type in (chess.ROOK, chess.QUEEN)
        for p in board.piece_map().values()
    )
    return has_heavy


def tags_for_move(
    board_before: chess.Board,
    board_after: chess.Board,
    *,
    mover: chess.Color,
    is_error: bool,
    missed_mate: bool,
    allowed_mate: bool,
) -> List[dict]:
    """Collect motif tags for a single played move.

    ``mover`` is the side that made the move. ``board_after`` therefore has the
    opponent to move, which is exactly when their winning captures expose the
    mover's hung material.
    """
    tags: List[dict] = []

    if missed_mate:
        tags.append(models.motif(models.MOTIF_MISSED_MATE))
    if allowed_mate:
        tags.append(models.motif(models.MOTIF_ALLOWED_MATE))

    if is_error:
        # Did the move hang material? Opponent is to move in board_after.
        opp_captures = winning_captures(board_after, min_gain=2)
        if opp_captures:
            top = opp_captures[0]
            tags.append(
                models.motif(
                    models.MOTIF_HANGING,
                    square=top["to"],
                    gain=top["gain"],
                )
            )
            # A capture that also forks counts as a fork the mover walked into.
            if detect_fork(board_after, not mover):
                tags.append(models.motif(models.MOTIF_FORK))

        # Did the mover miss a tactic that was available before moving?
        own_captures = winning_captures(board_before, min_gain=2)
        if own_captures and own_captures[0]["move"] != _played_uci(
            board_before, board_after
        ):
            tags.append(
                models.motif(
                    models.MOTIF_MISSED_TACTIC, best_capture=own_captures[0]["move"]
                )
            )

        if back_rank_weakness(board_after, mover):
            tags.append(models.motif(models.MOTIF_BACK_RANK))

    # De-duplicate by motif name, keeping the first (richest) occurrence.
    seen = set()
    unique = []
    for t in tags:
        if t["motif"] in seen:
            continue
        seen.add(t["motif"])
        unique.append(t)
    return unique


def _played_uci(board_before: chess.Board, board_after: chess.Board) -> str:
    """Recover the UCI of the move that turned ``board_before`` into ``after``.

    Falls back to empty string if it cannot be determined (defensive only).
    """
    try:
        move = board_after.move_stack[-1]
        return move.uci()
    except (IndexError, AttributeError):
        return ""
