"""chess-coach-mcp: a hybrid AI chess coach exposed as an MCP server.

Local Stockfish supplies grounded evaluations; the MCP host model supplies the
(Korean) coaching prose. See :mod:`chess_coach_mcp.server` for the tool surface.
"""

from .server import main

__version__ = "0.1.1"
__all__ = ["main", "__version__"]
