"""Fetch games (and a daily puzzle) from Lichess and Chess.com public APIs.

Both endpoints are unauthenticated for public data. Games are normalised into
:class:`~chess_coach_mcp.models.GameRecord`. Network access is via ``httpx``;
an :class:`httpx.AsyncClient` may be injected for reuse/testing.
"""

from __future__ import annotations

import io
import json
import re
from typing import List, Optional

import chess.pgn
import httpx

from .config import get_settings
from .models import GameRecord

LICHESS_API = "https://lichess.org"
CHESSCOM_API = "https://api.chess.com"

# Map our generic speed label to each provider's vocabulary.
_LICHESS_PERF = {
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "classical",
    "correspondence": "correspondence",
}
_CHESSCOM_TIMECLASS = {
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "daily",
    "correspondence": "daily",
}


class SourceError(RuntimeError):
    """Raised on unexpected upstream responses (HTTP error, bad payload)."""


def _new_client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        timeout=s.http_timeout,
        headers={"User-Agent": s.user_agent},
        follow_redirects=True,
    )


async def _get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET that converts transport-level httpx errors into SourceError.

    Keeps the documented contract that every source failure is a SourceError,
    so the MCP tools return a clean structured error rather than crashing on a
    connection refused / timeout / DNS failure.
    """
    try:
        return await client.get(url, **kwargs)
    except httpx.HTTPError as exc:
        raise SourceError(f"Network error contacting {url}: {exc}") from exc


def _json(resp: httpx.Response, source: str) -> dict:
    """Parse a JSON body, converting a malformed/non-JSON body into SourceError."""
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError(f"Malformed JSON response from {source}: {exc}") from exc


def _header(pgn_headers, *keys: str) -> Optional[str]:
    for k in keys:
        v = pgn_headers.get(k)
        if v and v != "?":
            return v
    return None


# --- Lichess ---------------------------------------------------------------

def _lichess_record(obj: dict) -> GameRecord:
    players = obj.get("players", {})

    def _name(side: str) -> str:
        side_obj = players.get(side, {})
        user = side_obj.get("user") or {}
        if user.get("name"):
            return user["name"]
        if "aiLevel" in side_obj:
            return f"Stockfish level {side_obj['aiLevel']}"
        return "Anonymous"

    def _rating(side: str) -> Optional[int]:
        return players.get(side, {}).get("rating")

    winner = obj.get("winner")
    status = obj.get("status", "")
    if winner == "white":
        result = "1-0"
    elif winner == "black":
        result = "0-1"
    elif status in ("draw", "stalemate"):
        result = "1/2-1/2"
    else:
        # No winner and not a real draw: aborted / noStart / unknownFinish /
        # ongoing. Mark unknown ('*') so it is excluded from score stats, not
        # counted as a half-point draw.
        result = "*"

    clock = obj.get("clock")
    if clock:
        time_control = f"{clock.get('initial', 0)}+{clock.get('increment', 0)}"
    else:
        time_control = obj.get("speed")

    opening = obj.get("opening") or {}
    game_id = obj.get("id", "")
    return GameRecord(
        source="lichess",
        game_id=game_id,
        url=f"{LICHESS_API}/{game_id}" if game_id else LICHESS_API,
        pgn=obj.get("pgn", ""),
        white=_name("white"),
        black=_name("black"),
        result=result,
        white_rating=_rating("white"),
        black_rating=_rating("black"),
        time_control=time_control,
        speed=obj.get("speed"),
        opening=opening.get("name"),
        eco=opening.get("eco"),
        played_at=_ms_to_iso(obj.get("createdAt")),
    )


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    import datetime

    return datetime.datetime.fromtimestamp(
        ms / 1000, tz=datetime.timezone.utc
    ).isoformat()


async def fetch_lichess_games(
    username: str,
    max_games: int,
    *,
    speed: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[GameRecord]:
    if not username:
        raise SourceError("A Lichess username is required.")
    params = {
        "max": max_games,
        "pgnInJson": "true",
        "opening": "true",
        "clocks": "false",
        "evals": "false",
        "sort": "dateDesc",
    }
    if speed and speed in _LICHESS_PERF:
        params["perfType"] = _LICHESS_PERF[speed]

    owns_client = client is None
    client = client or _new_client()
    try:
        resp = await _get(
            client,
            f"{LICHESS_API}/api/games/user/{username}",
            params=params,
            headers={"Accept": "application/x-ndjson"},
        )
        if resp.status_code == 404:
            raise SourceError(f"Lichess user '{username}' not found.")
        if resp.status_code != 200:
            raise SourceError(
                f"Lichess returned HTTP {resp.status_code} for user '{username}'."
            )
        records = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(_lichess_record(json.loads(line)))
            except json.JSONDecodeError as exc:
                raise SourceError(
                    f"Malformed NDJSON line from Lichess: {exc}"
                ) from exc
        return records
    finally:
        if owns_client:
            await client.aclose()


# --- Chess.com -------------------------------------------------------------

_ECO_FROM_URL = re.compile(r"/openings/([^/?#]+)")


def _chesscom_record(obj: dict) -> GameRecord:
    pgn = obj.get("pgn", "")
    headers = {}
    if pgn:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is not None:
            headers = game.headers

    white = obj.get("white", {})
    black = obj.get("black", {})
    w_res = white.get("result")
    b_res = black.get("result")
    if w_res == "win":
        result = "1-0"
    elif b_res == "win":
        result = "0-1"
    elif w_res is None and b_res is None:
        result = "*"
    else:
        result = "1/2-1/2"

    opening = _header(headers, "Opening")
    eco = _header(headers, "ECO")
    if not opening:
        m = _ECO_FROM_URL.search(obj.get("eco", "") or "")
        if m:
            opening = m.group(1).replace("-", " ")

    end_time = obj.get("end_time")
    played_at = None
    if end_time:
        import datetime

        played_at = datetime.datetime.fromtimestamp(
            end_time, tz=datetime.timezone.utc
        ).isoformat()

    return GameRecord(
        source="chesscom",
        game_id=str(obj.get("uuid", "") or obj.get("url", "")),
        url=obj.get("url", CHESSCOM_API),
        pgn=pgn,
        white=white.get("username", "?"),
        black=black.get("username", "?"),
        result=result,
        white_rating=white.get("rating"),
        black_rating=black.get("rating"),
        time_control=obj.get("time_control"),
        speed=obj.get("time_class"),
        opening=opening,
        eco=eco,
        played_at=played_at,
    )


async def fetch_chesscom_games(
    username: str,
    max_games: int,
    *,
    speed: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[GameRecord]:
    if not username:
        raise SourceError("A Chess.com username is required.")
    username = username.lower()
    want_class = _CHESSCOM_TIMECLASS.get(speed) if speed else None

    owns_client = client is None
    client = client or _new_client()
    try:
        arch_resp = await _get(
            client, f"{CHESSCOM_API}/pub/player/{username}/games/archives"
        )
        if arch_resp.status_code == 404:
            raise SourceError(f"Chess.com user '{username}' not found.")
        if arch_resp.status_code != 200:
            raise SourceError(
                f"Chess.com returned HTTP {arch_resp.status_code} for '{username}'."
            )
        archives = _json(arch_resp, "Chess.com").get("archives", [])
        records: List[GameRecord] = []
        # Walk archives newest-first until we have enough games.
        for archive_url in reversed(archives):
            month_resp = await _get(client, archive_url)
            if month_resp.status_code != 200:
                continue
            try:
                games = _json(month_resp, "Chess.com").get("games", [])
            except SourceError:
                continue  # skip one unparseable month rather than aborting all
            for obj in reversed(games):  # newest game within the month first
                if want_class and obj.get("time_class") != want_class:
                    continue
                if obj.get("rules", "chess") != "chess":
                    continue  # skip chess960/bughouse/etc.
                records.append(_chesscom_record(obj))
                if len(records) >= max_games:
                    return records
        return records
    finally:
        if owns_client:
            await client.aclose()


# --- Dispatch + puzzle -----------------------------------------------------

async def fetch_games(
    username: str,
    source: str = "lichess",
    max_games: int = 10,
    *,
    speed: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[GameRecord]:
    source = (source or "lichess").lower()
    cap = get_settings().max_games_cap
    max_games = max(1, min(int(max_games), cap))
    if source == "lichess":
        return await fetch_lichess_games(
            username, max_games, speed=speed, client=client
        )
    if source in ("chesscom", "chess.com", "chess_com"):
        return await fetch_chesscom_games(
            username, max_games, speed=speed, client=client
        )
    raise SourceError(f"Unknown source '{source}'. Use 'lichess' or 'chesscom'.")


async def fetch_daily_puzzle(
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Fetch Lichess' daily puzzle and resolve it to a FEN + solution.

    Returns ``{id, rating, themes, fen, side_to_move, solution}`` where
    ``solution`` is the list of UCI moves. Best-effort; raises SourceError on
    failure.
    """
    owns_client = client is None
    client = client or _new_client()
    try:
        resp = await _get(client, f"{LICHESS_API}/api/puzzle/daily")
        if resp.status_code != 200:
            raise SourceError(f"Lichess puzzle API returned HTTP {resp.status_code}.")
        data = _json(resp, "Lichess")
        puzzle = data.get("puzzle", {})
        game = data.get("game", {})
        pgn_moves = game.get("pgn", "")
        initial_ply = puzzle.get("initialPly", 0)

        board = chess.Board()
        san_or_uci = pgn_moves.split()
        played = 0
        for token in san_or_uci:
            if played >= initial_ply:
                break
            try:
                board.push_uci(token)
            except ValueError:
                try:
                    board.push_san(token)
                except ValueError:
                    break
            played += 1

        return {
            "id": puzzle.get("id"),
            "rating": puzzle.get("rating"),
            "themes": puzzle.get("themes", []),
            "fen": board.fen(),
            "side_to_move": "white" if board.turn == chess.WHITE else "black",
            "solution": puzzle.get("solution", []),
            "url": f"{LICHESS_API}/training/{puzzle.get('id')}"
            if puzzle.get("id")
            else None,
        }
    finally:
        if owns_client:
            await client.aclose()
