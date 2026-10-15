---
name: chess-coach
description: Engine-grounded chess coaching through the chess-coach MCP server (local Stockfish + Lichess/Chess.com). Use when the user wants a chess game reviewed (PGN or a recent online game), a position explained (FEN), their recurring weaknesses diagnosed from their recent Lichess or Chess.com games, or training drills built from their own blunders. Also use for Korean requests such as 체스 기보 분석, 약점 진단, 리체스, 체스닷컴, 퍼즐.
license: MIT
compatibility: Needs the chess-coach MCP server (`uvx chess-coach-mcp`, Python 3.11+) and a local Stockfish binary. Fetching games needs network access to lichess.org or chess.com.
metadata:
  author: parkseokjune
  version: "0.1.2"
  repository: https://github.com/parkseokjune/chess-coach-mcp
---

# Chess coach

Stockfish is the judge; you are the explainer. The chess-coach MCP tools return
engine-grounded facts (evaluations, move classifications, tactical motifs,
cross-game weakness statistics). Your job is to turn those facts into clear,
personal coaching.

**Never state an evaluation, a best move or a variation that did not come from
a tool result.** LLMs evaluate chess positions poorly; that is the whole reason
this server exists. If you need a fact you don't have, call a tool.

## Before you start

- The tools are `engine_status`, `render_board`, `fetch_recent_games`,
  `analyze_position`, `analyze_game`, `diagnose_weaknesses` and
  `recommend_drills`. Your host may prefix them (for example
  `mcp__chess-coach__analyze_game`).
- If none of them are available, the server isn't installed. Point the user to
  [Setup](#setup) rather than analysing the chess yourself.
- Every tool returns `{"error": ..., "error_type": ...}` instead of raising. On
  an `EngineError`, call `engine_status` and pass on its `hint`. On a
  `SourceError`, the message says what went wrong (unknown user, network
  error, or an HTTP status such as 429 for rate limiting). Relay it and ask
  the user to check the username or site, or to retry later.

## Pick the workflow

| The user… | Call |
|---|---|
| pastes a PGN, "review this game" | `analyze_game(pgn, user_color=…)` |
| "review my last game", gives a username | `fetch_recent_games(username, source, max_games=5)` → choose the game → `analyze_game(game.pgn, user_color=<their colour>)` |
| gives a FEN, "what's best here?" | `analyze_position(fen)` |
| "show me this position" | `render_board(fen)` (no engine needed) |
| "what are my weaknesses?" | `diagnose_weaknesses(username, source)` |
| "give me training / puzzles from my games" | `recommend_drills(username, source)` |

Arguments that matter:

- `source` is `"lichess"` (default) or `"chesscom"`. If the user hasn't said
  which site, ask. A username on the wrong site gives wrong or empty results.
- `speed` (`bullet` / `blitz` / `rapid` / `classical`) filters
  `fetch_recent_games` and `diagnose_weaknesses`. Pass it when the user names
  a time control. `recommend_drills` does not take it.
- `user_color`: when you know the user's username, set it from the game's
  `white` / `black` fields. It focuses `worst_moments` and `motif_counts` on
  the user instead of pooling both sides.

### Cost and latency

- `diagnose_weaknesses` and `recommend_drills` run Stockfish over every move of
  every fetched game. The defaults (15 games, depth 12) can take a few minutes.
  Tell the user it will take a moment. For a quick first look use
  `max_games=5`–`8`. The hard cap is 50 games.
- `recommend_drills` runs a full diagnosis internally. **Don't call
  `diagnose_weaknesses` and then `recommend_drills` for the same request**;
  that does all the work twice. If the user wants a report and drills, call
  `recommend_drills` once (it returns `focus_areas` + `drills`). If you already
  hold a diagnosis, build drills from its `example_blunders`, which carry
  `fen_before`, the played `san` and `best_move_san`.
- Keep the default depths. Raise `analyze_position` depth to 20–24 only for a
  deliberate deep look at one position. Lower `analyze_game` depth to 10–12
  for long games when speed matters.
- `analyze_game` stops at `max_plies` (default 200). Check `truncated`.

## Reading the results

**Perspective.** Every centipawn and win% value is from the point of view of
the side to move (for per-move fields, the side that made the move). Positive
means good for that side. Convert carefully when you say "White is better".

**Classification** is by the drop in win probability (Lichess model):
inaccuracy ≥ 5 points, mistake ≥ 10, blunder ≥ 20. `best` means the move
matched the engine's top choice.

Key fields:

- `analyze_game`: `summary.white` / `summary.black` (`accuracy`, `acpl`,
  counts per class), `summary.by_phase`, `motif_counts`, and `worst_moments[]`
  with `san`, `best_move_san`, `win_drop`, `motifs`, `fen_before` and
  `lichess_url`. `moves[]` has the full per-ply detail.
- `analyze_position`: `eval_cp` / `eval_mate`, `win_pct_side_to_move`,
  `best_line` (`move_san`, `pv_san`), `lines[]`, `material.balance` (White
  minus Black, in pawns), `fork_threats`, `pins_against_opponent`, `in_check`,
  `board_ascii` and `lichess_url`. A finished game returns `game_over: true`
  with `outcome` instead.
- `diagnose_weaknesses`: `games_analyzed`, `overall`, `by_phase` (`acpl`,
  `error_rate`), `motif_blind_spots[]` (`count`, `examples`), `openings[]`
  (`score_pct`, `acpl`), `time_trouble_proxy`, `top_weaknesses[]` (ranked:
  `theme`, `category`, `detail`, `example_fens`), `example_blunders[]` and
  `notes`.
- `recommend_drills`: `focus_areas`, `drills[]` (`fen`, `side_to_move`,
  `board_ascii`, `lichess_url`, `prompt`, `your_move_san`, `answer_san`,
  `theme`), `bonus_puzzle` and `coaching_hint`.

Respect the limits of the data:

- **Motif tags are heuristics** (a one-ply static-exchange check, geometric fork
  and pin detection). They group mistakes into human themes. Phrase them as
  "this looks like a hanging piece" and check them against the engine line
  before you assert them.
- **`time_trouble_proxy` has no clock data.** It counts blunders after move 30.
  Say "you blunder more late in the game", not "you were short of time".
- **Small samples are tentative.** If `games_analyzed` is under 5, or a motif
  recurred only twice, say the pattern is worth watching rather than proven.
- If `games_analyzed` is 0, read `notes`: usually a wrong username, the wrong
  site, or no public games.

## How to coach

1. **Lead with what matters.** One to three points, each tied to a concrete
   position from the user's own games. Don't dump the statistics.
2. **Explain the why.** For each key moment, contrast the played move with the
   engine's move. What does the engine's move threaten or defend? What did the
   played move allow? Use `pv_san` to show the follow-up. If you can't see the
   reason, call `analyze_position` on `fen_before` (or on the position after
   the played move, to see the refutation) instead of guessing.
3. **Show the board.** Print `board_ascii` in a code block and give
   `lichess_url` so the user can explore. Never draw a board from memory.
4. **Make the numbers human.** "That threw away about a third of your winning
   chances" or "about a pawn and a half" reads better than "−153 cp".
5. **Treat drills as quizzes.** Show one position and its `prompt`, ask for the
   user's move, and reveal `answer_san` only after they answer or ask. Then
   connect it to the matching focus area. One drill at a time.
6. **End with a next step**: a specific drill, an opening line to revisit, or
   a habit, such as checking every capture and check the opponent has before
   moving.

## Coaching in Korean (한국어 코칭)

When the user writes in Korean, coach in Korean. Every categorical value ships
with a `*_ko` label (`classification_ko`, `phase_ko`, `motif_ko`, `theme_ko`,
`prompt_ko`). Use those labels instead of translating, so the terms stay
consistent: 대실수 / 실수 / 부정확수, 오프닝 / 미들게임 / 엔드게임,
무방비 기물(행잉), 포크, 핀, 백랭크 약점. Leave SAN moves (Nf3, Qxd5) as
they are. 백 = White, 흑 = Black.

## Setup

If the tools are missing, tell the user:

1. Install Stockfish: `brew install stockfish` (macOS) or
   `apt install stockfish` (Debian/Ubuntu), or set `STOCKFISH_PATH`.
2. Install the server and this skill together:
   - **Claude Code**: `/plugin marketplace add parkseokjune/chess-coach-mcp`,
     then `/plugin install chess-coach@chess-coach-mcp` (needs `uv`). On
     Claude Code 2.1.275 or later, one step:
     `/plugin install chess-coach --marketplace parkseokjune/chess-coach-mcp`.
   - **Any other MCP client**: register a stdio server with command `uvx` and
     args `["chess-coach-mcp"]`, then add this skill folder to the agent's
     skills directory.

## Example

> 내 리체스 약점 진단해줘. 아이디 `myname`

1. Say the analysis takes a minute or two, then call
   `diagnose_weaknesses("myname", source="lichess", max_games=10)`.
2. Open with `top_weaknesses[0]`, for example `hanging_piece` recurring 4
   times. Show one of its `example_fens` with `render_board`, give the Lichess
   link, and explain in Korean why `best_move_san` beats the move played.
3. Cover the next one or two weaknesses (a weak phase, a leaky opening) in the
   same way, more briefly.
4. Offer drills. Quiz the user on `example_blunders` that match the top theme,
   one at a time, revealing each answer after they try.
