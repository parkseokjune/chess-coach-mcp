"""Stockfish (UCI) wrapper plus the evaluation math used everywhere else.

A single Stockfish process is shared behind a lock. The engine library is
synchronous, so async callers should wrap :func:`evaluate` in
``asyncio.to_thread``.

Evaluation is expressed two ways:

* **centipawns** from the side-to-move's perspective (mate mapped to a large
  finite value), and
* **win percentage** via Lichess' logistic model, which is what move
  classification thresholds are defined against. Win% behaves far better than
  raw centipawns in already-winning or already-losing positions.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import List, Optional

import chess
import chess.engine

from .config import find_stockfish, get_settings


class EngineError(RuntimeError):
    """Raised when Stockfish cannot be located or started."""


# --- Pure evaluation helpers (no engine needed; trivially unit-testable) ----

def win_percent(cp: int) -> float:
    """Convert centipawns (side-to-move POV) to a 0-100 win percentage.

    Uses the Lichess model: ``50 + 50 * (2 / (1 + e^(-0.00368208 * cp)) - 1)``.
    """
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def move_accuracy(win_before: float, win_after: float) -> float:
    """Per-move accuracy (0-100) from the win% drop, Lichess' formula.

    ``win_before``/``win_after`` are both from the moving side's perspective.
    """
    win_loss = max(0.0, win_before - win_after)
    acc = 103.1668 * math.exp(-0.04354 * win_loss) - 3.1669
    return max(0.0, min(100.0, acc))


@dataclass
class Evaluation:
    """Normalised result of analysing one position (side-to-move POV)."""

    cp: int  # centipawns, side-to-move POV (mate mapped to +/- mate_score)
    mate: Optional[int]  # signed mate distance, side-to-move POV, else None
    best_move: Optional[str]  # UCI of the top move, or None at game end
    pv: List[str]  # principal variation (UCI) of the top line
    lines: List[dict]  # one dict per multipv line: {move, cp, mate, pv}
    depth: Optional[int] = None

    @property
    def win_pct(self) -> float:
        return win_percent(self.cp)


def _pov_cp(score: chess.engine.PovScore, turn: chess.Color, mate_score: int) -> int:
    return int(score.pov(turn).score(mate_score=mate_score))


def _pov_mate(score: chess.engine.PovScore, turn: chess.Color) -> Optional[int]:
    return score.pov(turn).mate()


# --- Engine process wrapper -------------------------------------------------

class StockfishEngine:
    """Thread-safe, lazily-created singleton around one Stockfish process."""

    _instance: Optional["StockfishEngine"] = None
    _instance_lock = threading.Lock()

    def __init__(self, path: str, *, threads: int, hash_mb: int):
        self.path = path
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(path)
        except (chess.engine.EngineError, OSError) as exc:
            # A path that exists/executes but is not a working UCI engine, or a
            # binary that vanished/became unexecutable since discovery.
            raise EngineError(
                f"Failed to start Stockfish at '{path}': {exc}. Ensure it is a "
                "working UCI engine, or set STOCKFISH_PATH to a valid binary."
            ) from exc
        # Best-effort configuration; ignore unsupported options.
        try:
            self._engine.configure({"Threads": threads, "Hash": hash_mb})
        except Exception:
            pass
        self._lock = threading.Lock()

    @classmethod
    def get(cls, path: Optional[str] = None) -> "StockfishEngine":
        with cls._instance_lock:
            if cls._instance is None:
                resolved = find_stockfish(path)
                if not resolved:
                    raise EngineError(
                        "Stockfish executable not found. Install it "
                        "(`brew install stockfish` or `apt install stockfish`) "
                        "or set the STOCKFISH_PATH environment variable."
                    )
                s = get_settings()
                cls._instance = cls(
                    resolved, threads=s.engine_threads, hash_mb=s.engine_hash_mb
                )
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Tear down the shared engine (used by tests / clean shutdown)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def close(self) -> None:
        try:
            self._engine.quit()
        except Exception:
            pass

    def evaluate(
        self,
        board: chess.Board,
        *,
        depth: Optional[int] = None,
        movetime: Optional[float] = None,
        multipv: int = 1,
    ) -> Evaluation:
        """Analyse ``board`` and return a normalised :class:`Evaluation`.

        ``board`` must not be terminal (checkmate/stalemate); callers handle
        those cases explicitly since Stockfish cannot analyse a finished game.
        """
        if board.is_game_over():
            raise EngineError("Cannot analyse a terminal position.")

        settings = get_settings()
        if depth is None and movetime is None:
            depth = settings.default_position_depth
        limit = chess.engine.Limit(
            depth=depth if movetime is None else None, time=movetime
        )
        multipv = max(1, int(multipv))

        with self._lock:
            info = self._engine.analyse(board, limit, multipv=multipv)

        # python-chess returns a list when multipv is supplied.
        infos = info if isinstance(info, list) else [info]
        infos = [i for i in infos if i.get("score") is not None]
        if not infos:
            raise EngineError("Stockfish returned no evaluation.")

        turn = board.turn
        mate_score = settings.mate_score
        lines: List[dict] = []
        for entry in infos:
            pv_moves = entry.get("pv") or []
            lines.append(
                {
                    "move": pv_moves[0].uci() if pv_moves else None,
                    "cp": _pov_cp(entry["score"], turn, mate_score),
                    "mate": _pov_mate(entry["score"], turn),
                    "pv": [m.uci() for m in pv_moves],
                }
            )

        top = lines[0]
        reported_depth = infos[0].get("depth")
        return Evaluation(
            cp=top["cp"],
            mate=top["mate"],
            best_move=top["move"],
            pv=top["pv"],
            lines=lines,
            depth=int(reported_depth) if reported_depth is not None else None,
        )
