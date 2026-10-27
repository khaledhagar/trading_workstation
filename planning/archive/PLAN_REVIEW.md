# trading_workstation — Spec Review Log

*Moved out of PLAN.md §13. Every item here is resolved and its outcome is already in PLAN.md §5–§12.*

## Review: Questions, Clarifications & Simplification Opportunities

*Added during documentation review. Items are grouped by theme; each one flags a gap or ambiguity that parallel agents could resolve inconsistently if left open. Suggested resolutions are proposals, not decisions.*

### 13.1 Missing Contracts Between Agents (highest priority)

> **✅ Resolved.** All five items below are now specified in the spec itself: the SSE event format in §6 (SSE Streaming), and conventions, errors, response contracts and the new `GET /api/chat/history` endpoint in §8. The `POST /api/chat` contract also resolves item 18: action outcomes are returned per action, with no second LLM call.

Frontend and backend agents work in parallel, so these payload shapes need to be pinned down before implementation starts.

1. **SSE event format is unspecified.** Is it one SSE event per ticker, or one event carrying a batch of all tickers every ~500ms? What is the event name (default `message` or a named event such as `price`)? What are the field names and timestamp format? *Suggestion:* one event per tick holding a JSON object keyed by ticker, e.g. `{"AAPL": {"ticker": "AAPL", "price": 190.12, "previous_price": 190.05, "timestamp": "2026-01-01T12:00:00Z", "direction": "up"}}`, with `direction` in `up | down | flat`.
2. **REST response shapes are unspecified** for `GET /api/portfolio`, `GET /api/portfolio/history`, `GET /api/watchlist`, `POST /api/portfolio/trade` and `POST /api/chat`. Add example JSON for each.
3. **The error response format is unspecified.** *Suggestion:* use FastAPI's default `{"detail": "..."}`, with 400 for validation failures (insufficient cash or shares, unknown ticker), 404 for removing a ticker that isn't watched, and 409 for adding a duplicate ticker (or make the add idempotent and return 200).
4. **There is no endpoint to load chat history.** Messages are persisted in `chat_messages`, but the frontend has no way to fetch them, so the chat panel is empty after every reload. Either add `GET /api/chat/history` or state explicitly that history is only used as LLM context.
5. **Timestamps:** state that every timestamp is ISO 8601 in UTC, with a `Z` suffix.

### 13.2 Market Data & Pricing

> **✅ Resolved** in §6: item 6 → reference price plus `change_percent` in the SSE and watchlist payloads; item 7 → Tracked Tickers; item 8 → Ticker Rules and per-source unknown-ticker handling; item 9 → trades with no price return 400; item 10 → single multi-ticker snapshot call per poll; item 11 → Price History (frontend-only, no server history).

6. **"Daily change %" has no defined baseline.** The simulator has no market open or previous close. *Suggestion:* define it as change from the seed price (simulator) or the previous close (Massive), and have the backend include it in the SSE payload so the frontend doesn't have to guess.
7. **Which tickers get priced?** §6 says "all tickers known to the system ≈ watchlist". But if the user removes a ticker they still hold, that position can no longer be valued. *Suggestion:* the tracked set is watchlist ∪ held positions.
8. **What happens when an unknown or arbitrary ticker is added?** The simulator needs a seed price and volatility for tickers outside its defaults, and Massive may return nothing for an invalid symbol. *Suggestion:* the simulator assigns a random seed price (e.g. $50–$300) with default volatility; the Massive path rejects the add if the ticker can't be resolved. Also define ticker normalization (uppercase, trimmed, a pattern like `^[A-Z.]{1,10}$`).
9. **How are trades handled before a ticker has a price?** A just-added ticker can have an empty cache entry. *Suggestion:* reject the trade with a clear error.
10. **Massive rate limits:** 5 calls/min with 10+ tickers only works if one multi-ticker snapshot call is made per poll. State this, and name the endpoint.
11. **Main chart data source:** the main chart, like the sparklines, has no data at page load because there's no server-side price history. Confirm this is acceptable (the simplest option). The alternative is a small in-memory ring buffer per ticker exposed via an endpoint.

### 13.3 Portfolio & Trading Logic

> **✅ Resolved** in §8 (Trading Rules, Persistence & Concurrency) and §7 (portfolio_snapshots): item 12 → fractional to 4 decimals, cash rounded to cents; item 13 → the row is deleted; item 14 → sells leave `avg_cost` unchanged, and a re-buy starts fresh; item 15 → buying an unwatched ticker auto-adds it to the watchlist; item 16 → one `BEGIN IMMEDIATE` transaction per trade, WAL mode; item 17 → snapshots are always recorded, never pruned, and history returns the last 1,000.

12. **Quantity rules:** must be > 0. Are fractional shares allowed from the trade bar as well as from the LLM? What precision (e.g. up to 4 decimals)? Round cash to cents?
13. **Selling a full position:** delete the `positions` row, or keep it with quantity 0? §12 says a position "disappears", which implies delete. Say so explicitly.
14. **Average cost on sells:** confirm that sells leave `avg_cost` unchanged and that a re-buy after a full exit starts fresh.
15. **Can users trade a ticker that isn't in the watchlist?** If yes, is it auto-added to the watchlist, or only priced because it's now a held position (see item 7)?
16. **Atomicity:** each trade (cash update, position upsert, trade log, snapshot) should run in a single SQLite transaction. The snapshot task and trades may write at the same time, so specify one connection per request with WAL mode, or a single write lock.
17. **Snapshot growth:** a snapshot every 30 seconds adds about 2,880 rows per day, and `GET /api/portfolio/history` has no limit. *Suggestion:* return at most the last N points (e.g. 500), or downsample. Also confirm whether snapshots are recorded when there are no positions (the value would just be the flat cash balance).

### 13.4 LLM Integration

> **✅ Resolved** in §9: item 18 → per-action outcomes with no second call, and the system prompt phrases actions as intent; item 19 → last 20 messages, with action outcomes summarized into the history; item 20 → all schema fields required, arrays may be empty, `Literal` enums; item 21 → Failure Handling (200 with an apology message, both messages stored, no retry); item 22 → a mock rules table running through the real execution path; item 23 → *correction:* the skill really is named `cerebras-inference` (its folder is `cerebras/`), so §9 now cites the path. Also added: use `acompletion` so the LLM call doesn't block SSE.

18. **Contradiction around trade failures.** The LLM writes its `message` *before* any trades run, so it can't "inform the user" about a validation failure without a second LLM call. *Suggestion (simpler):* make no second call. Return per-action results (`status: "executed" | "failed"`, `error`) next to the LLM's message, and have the frontend render failures inline.
19. **Conversation history window:** how many prior messages are sent to the LLM (e.g. the last 20)? Are the stored `actions` of earlier messages included in that context?
20. **Structured output strictness:** strict JSON-schema modes usually require every property to be listed as required. *Suggestion:* make `trades` and `watchlist_changes` required arrays that may be empty, rather than optional.
21. **Malformed or failed LLM response:** define the fallback. *Suggestion:* return 200 with a friendly error message and no actions, and still store the user message.
22. **Mock mode behavior isn't defined**, but E2E tests depend on it. Specify the deterministic rules. *Suggestion:* a message containing "buy" executes a buy of 1 AAPL, "add <TICKER>" adds that ticker to the watchlist, and anything else returns a fixed text reply.
23. **Skill name:** §9 refers to the "cerebras-inference skill", but the skill available in this repo is named `cerebras`. Align the name.

### 13.5 Database & Schema

> **✅ Resolved**: item 24 → §7 Schema says `users_profile.id` is the user id; item 25 → §7 initializes once at startup in the FastAPI lifespan, with idempotent `CREATE TABLE IF NOT EXISTS`, seeding only when the default user row is missing (§4 wording updated to match); item 26 → the new optional `DB_PATH` env var in §5 defaults to `<project root>/db/trading_workstation.db`, and the Dockerfile in §11 sets `/app/db/trading_workstation.db`.

24. **`users_profile` has no `user_id` column**, which contradicts "all tables include a `user_id` column". Clarify that `id` serves as the user id for this table.
25. **Initialization timing:** "on startup (or first request)". Pick one. *Suggestion:* at application startup (FastAPI lifespan). That is deterministic and avoids a race between concurrent first requests.
26. **Database path when running locally:** in the container the path is `/app/db/trading_workstation.db`, but running `uv run` inside `backend/` needs `../db/trading_workstation.db`. *Suggestion:* use a `DB_PATH` env var with a sensible default.

### 13.6 Docker, Deployment & Environment

> **✅ Resolved**: item 27 → a named volume `trading-workstation-data` (§11), with the top-level `db/` used only for local runs (§4 updated); item 28 → `--env-file` in Docker, `load_dotenv(<project root>/.env)` locally without overriding (§5); item 29 → the app starts, and chat returns a "not configured" assistant message (§5); item 30 → §11 Static File Serving (API routers first, `StaticFiles(html=True)` mounted last, mount skipped if the build is missing).

27. **Volume contradiction:** §11 uses a *named* volume (`trading-workstation-data:/app/db`), but then says the project's `db/` directory maps to `/app/db`, which would be a *bind* mount. Pick one. A named volume is simpler and avoids Windows path issues; if you choose it, the top-level `db/` directory is only for local, non-Docker runs.
28. **`.env` loading:** in Docker it's passed with `--env-file`, but for local dev the backend runs from `backend/` while `.env` lives at the project root. Specify how the backend finds it (e.g. `python-dotenv` pointed at the repo root, or just rely on the environment).
29. **Missing `OPENROUTER_API_KEY`:** should the app start and run chat in a degraded mode, or fail fast? *Suggestion:* start normally, and have the chat endpoint return a clear error.
30. **Static serving:** confirm that FastAPI mounts the static export at `/` *after* the API routers, so `/api/*` always takes precedence. Also confirm the Next.js export setting (`trailingSlash`, etc.) works with `StaticFiles(html=True)`.

### 13.7 Frontend

> **✅ Resolved** in §10: item 31 → Connection Status table (readyState plus a 5s staleness check, and manual reconnect after `CLOSED`); item 32 → Header Values (total computed on the frontend from SSE plus positions, with refetch triggers listed); item 33 → Lightweight Charts for the main and P&L charts, inline SVG sparklines, Recharts `Treemap` for the heatmap; item 34 → Empty & Loading States table. Also added: Heatmap Colors (±5% clamped red–gray–green scale), which the E2E "correct colors" check needs.

31. **Connection status mapping:** `EventSource` reports only `CONNECTING`, `OPEN` and `CLOSED`. Define "reconnecting" as `CONNECTING` after the connection was previously open, and "disconnected" as `CLOSED` (or no events for more than N seconds).
32. **Live total value in the header:** is it computed on the frontend from SSE prices plus positions, or re-fetched from `/api/portfolio`? *Suggestion:* compute it on the frontend and re-fetch the portfolio after each trade or chat action.
33. **Charting library:** "Lightweight Charts or Recharts" is described as canvas-based, but Recharts renders SVG. Also, neither library provides a treemap in the same way (Recharts has one, Lightweight Charts doesn't). *Suggestion:* Lightweight Charts for the price and P&L charts, plus Recharts `Treemap` (or a small custom div-based treemap) for the heatmap.
34. **Empty states:** define what the heatmap, positions table and P&L chart show before any trade has been made.

### 13.8 Opportunities to Simplify

> **✅ Resolved.** Outcome of each suggestion below, in order:
>
> - Drop root `docker-compose.yml` → **adopted**, removed from §4
> - Composite primary keys → **adopted** in §7 (`watchlist` and `positions` keyed by `(user_id, ticker)`; `trades`, `portfolio_snapshots` and `chat_messages` keep UUIDs, since they're logs with many rows per key)
> - Skip the second LLM round-trip → **already adopted** in §9 (13.4)
> - Frontend-only price history → **already adopted** in §6 (13.2)
> - Run Playwright from the host → **rejected** as a replacement: the container stays the canonical runner (reproducible, no local browser installs on Windows). Host runs are supported as an option via `BASE_URL` (§12)
> - Limit frontend unit tests → **adopted** in §12, with a concrete list of logic units
> - Longer snapshot interval / only record with positions → **rejected**: it conflicts with 13.3, which records snapshots always so the P&L chart has data from startup; ~2,880 rows/day is negligible

- **Drop `docker-compose.yml` at the root.** The start/stop scripts already cover running the app, and a second path to maintain adds little.
- **Use composite primary keys** `(user_id, ticker)` for `watchlist` and `positions` instead of a UUID `id` plus a UNIQUE constraint. That means one fewer column, and upserts become trivial.
- **Skip the second LLM round-trip** for failed trades (see item 18).
- **Frontend-only price history** for both the sparklines and the main chart (see item 11). This avoids any server-side history store.
- **Consider running Playwright from the host** (`npx playwright test` against the running container) instead of a dedicated Playwright container in `docker-compose.test.yml`. This is less infrastructure, although the containerized approach is more reproducible in CI, so it's a tradeoff worth a conscious decision.
- **Frontend unit tests:** limit them to logic-heavy pieces (price flash, P&L calculations, the SSE hook), and let the E2E tests cover rendering and CRUD flows. This avoids duplicate coverage.
- **Portfolio snapshots:** since a snapshot is recorded after every trade anyway, consider increasing the background interval (e.g. to 60s), or recording only while positions exist, to cut noise and table growth.
