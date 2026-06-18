"""Human-readable board rendering + Lichess analysis links.

The MCP returns data, not pictures — so these helpers let the host *show* a
board in plain text (works in any terminal) and hand back a clickable Lichess
analysis URL for a real interactive board. They are pure (no engine, no
network) and safe to call on any FEN.
"""

from __future__ import annotations

from typing import Optional, Union

import chess

LICHESS_ANALYSIS = "https://lichess.org/analysis/"

# Unicode chess glyphs: uppercase = White (outline), lowercase = Black (filled).
_UNICODE = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}


def lichess_analysis_url(fen: str) -> str:
    """Return a clickable Lichess analysis-board URL for ``fen``."""
    return LICHESS_ANALYSIS + fen.strip().replace(" ", "_")


def _as_board(fen_or_board: Union[str, chess.Board]) -> chess.Board:
    if isinstance(fen_or_board, chess.Board):
        return fen_or_board
    return chess.Board(fen_or_board)


def _resolve_orientation(value, board: chess.Board) -> chess.Color:
    if value in ("white", chess.WHITE):
        return chess.WHITE
    if value in ("black", chess.BLACK):
        return chess.BLACK
    return board.turn  # default: from the side-to-move's perspective


def board_text(
    fen_or_board: Union[str, chess.Board],
    *,
    unicode: bool = False,
    orientation=None,
    coords: bool = True,
) -> str:
    """Render a board as text.

    ``unicode=False`` uses letters (R N B Q K P / lowercase = Black) which are
    legible in every terminal; ``unicode=True`` uses chess glyphs. ``orientation``
    is 'white'/'black' (defaults to the side to move).
    """
    board = _as_board(fen_or_board)
    facing = _resolve_orientation(orientation, board)
    ranks = range(7, -1, -1) if facing == chess.WHITE else range(0, 8)
    files = range(0, 8) if facing == chess.WHITE else range(7, -1, -1)
    empty = "·" if unicode else "."

    lines = []
    for r in ranks:
        cells = []
        for f in files:
            piece = board.piece_at(chess.square(f, r))
            if piece is None:
                cells.append(empty)
            else:
                sym = piece.symbol()
                cells.append(_UNICODE[sym] if unicode else sym)
        line = " ".join(cells)
        if coords:
            line = f"{r + 1} {line}"
        lines.append(line)

    if coords:
        file_letters = list("abcdefgh")
        if facing == chess.BLACK:
            file_letters.reverse()
        lines.append("  " + " ".join(file_letters))
    return "\n".join(lines)


def render(fen: str, orientation: Optional[str] = None) -> dict:
    """Full render bundle for one position: text boards + Lichess link."""
    board = _as_board(fen)
    facing = _resolve_orientation(orientation, board)
    return {
        "fen": board.fen(),
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "orientation": "white" if facing == chess.WHITE else "black",
        "ascii": board_text(board, unicode=False, orientation=facing),
        "unicode": board_text(board, unicode=True, orientation=facing),
        "lichess_url": lichess_analysis_url(board.fen()),
    }
