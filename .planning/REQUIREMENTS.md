# Requirements: trading_workstation

**Defined:** 2026-11-03
**Core Value:** Open `http://localhost:8000` with one command and immediately see live-streaming prices you can trade, by hand or by asking the AI, with the portfolio updating in real time.

**Source of truth:** `planning/PLAN.md` (section refs in brackets) and `planning/MARKET_DATA_DESIGN.md` (market data implementation; it wins over the other market docs). Each requirement below must be implemented exactly as those documents specify (payload shapes, error strings, rounding, thresholds).

## v1 Requirements

### Foundation (FND)

- [ ] **FND-01**: Backend is a `uv` project in `backend/` (Python 3.12, FastAPI) that starts with `uv run uvicorn` locally [§4, §11]
- [ ] **FND-02**: Backend loads `<project root>/.env` via `python-dotenv` without overriding existing env vars; `.env.example` documents every variable [§5]
- [ ] **FND-03**: At startup (lifespan, before any request or background task) the backend resolves `DB_PATH` (default `<project root>/db/trading_workstation.db`), creates the parent dir, enables WAL and `busy_timeout=5000`, and creates all six tables idempotently [§7]
- [ ] **FND-04**: On first start the DB is seeded with user `default` ($10,000 cash) and the 10 default watchlist tickers; seeding never runs again once the `default` user exists [§7]
- [ ] **FND-05**: `GET /api/health` returns `{"status": "ok"}` [§8]
- [ ] **FND-06**: All API responses follow the conventions: JSON, ISO 8601 UTC `Z` timestamps (price timestamps with milliseconds), monetary values rounded to 2 decimals, errors as `{"detail": "..."}` with the specified status codes [§8 Conventions, Errors]
- [ ] **FND-07**: FastAPI serves the Next.js static export at `/` after all `/api/*` routes; when the static dir is missing it skips the mount and logs a notice [§11]

### Market Data (MKT)

- [ ] **MKT-01**: With no `MASSIVE_API_KEY`, a built-in GBM simulator produces prices every ~500ms with correlated sector moves, occasional 2–5% events, and realistic seed prices [§6, MARKET_DATA_DESIGN §5]
- [ ] **MKT-02**: With `MASSIVE_API_KEY` set, a Massive REST poller supplies prices in `snapshot` mode (paid: one multi-ticker call per poll, `MASSIVE_POLL_INTERVAL` default 15s, min 2) or `eod` mode (free: grouped daily, refreshed every 30 min), auto-detected from a 403 or forced via `MASSIVE_MODE` [§6, MARKET_DATA_DESIGN §6]
- [ ] **MKT-03**: Both sources implement one abstract `MarketDataSource` interface and write only to a shared in-memory `PriceCache` (latest, previous, reference price, timestamp); all consumers only read the cache [§6, MARKET_DATA_DESIGN §3–4]
- [ ] **MKT-04**: Tickers are trimmed, uppercased and validated against `^[A-Z][A-Z.]{0,9}$` (else 400 `"Invalid ticker"`) for manual and LLM input alike [§6 Ticker Rules]
- [ ] **MKT-05**: The tracked set is watchlist ∪ open positions; adding a ticker seeds the cache immediately (simulator seed price; Massive validation snapshot / loaded EOD data); unknown simulator tickers get a random $50–$300 seed [§6 Tracked Tickers]
- [ ] **MKT-06**: Massive rejects tickers it has no data for with 400 `"Unknown ticker: XYZ"` and returns 503 `"Market data unavailable, try again shortly"` when down, rate-limited or still loading (≤20s wait); the poller keeps last prices and retries [§6, §8 Errors]
- [ ] **MKT-07**: `GET /api/stream/prices` is a long-lived SSE stream emitting one unnamed event per ~500ms tick whose data is a JSON object keyed by ticker, with `ticker`, `price`, `previous_price`, `timestamp`, `direction`, `change_percent`, omitting unpriced tickers [§6 SSE Streaming]

### Watchlist (WATCH)

- [ ] **WATCH-01**: `GET /api/watchlist` returns the watched tickers with latest price fields (nulls when unpriced) [§8]
- [ ] **WATCH-02**: User can add a ticker via `POST /api/watchlist` (idempotent, returns the full list) [§8]
- [ ] **WATCH-03**: User can remove a ticker via `DELETE /api/watchlist/{ticker}` (404 if not watched; returns the full list); a held ticker keeps streaming [§6, §8]
- [ ] **WATCH-04**: User sees a watchlist panel with ticker, live price (green/red flash ~500ms on change), daily change %, and an inline-SVG sparkline accumulated from SSE since page load [§2, §10]
- [ ] **WATCH-05**: User can add and remove tickers from the watchlist panel, with backend error messages shown as-is [§2, §10]

### Trading (TRADE)

- [ ] **TRADE-01**: User can buy shares via `POST /api/portfolio/trade` at the current cached price; requires sufficient cash, else 400 `"Insufficient cash: need $X, have $Y"`; avg cost is the weighted average [§8 Trading Rules]
- [ ] **TRADE-02**: User can sell shares; requires held quantity ≥ sell quantity, else 400 `"Insufficient shares: have X, tried to sell Y"`; avg cost unchanged; position row deleted when remaining qty < 0.00005 [§8]
- [ ] **TRADE-03**: Quantity must be > 0 with ≤4 decimals (else 422); cash rounded to 2 decimals and quantities to 4 after each trade [§8]
- [ ] **TRADE-04**: Buying an unwatched ticker auto-adds it to the watchlist first (same validation and seeding); trading a ticker with no cached price returns 400 `"No price available for XYZ yet"` [§6, §8]
- [ ] **TRADE-05**: Each trade is a single `BEGIN IMMEDIATE` SQLite transaction (validate → cash → position upsert/delete → trade log → snapshot), so concurrent trades cannot both pass validation on stale balances [§8 Persistence & Concurrency]
- [ ] **TRADE-06**: The trade response contains the executed trade plus the full updated portfolio [§8 Response Contracts]
- [ ] **TRADE-07**: User can trade from a trade bar (ticker, quantity, Buy, Sell) with instant fill, no confirmation, and inline error display [§2, §10]

### Portfolio (PORT)

- [ ] **PORT-01**: `GET /api/portfolio` returns cash, positions value, total value, unrealized P&L and per-position quantity, avg cost, current price, market value, unrealized P&L and P&L % [§8]
- [ ] **PORT-02**: Portfolio snapshots are recorded at startup, every 30s by a background task (even with no positions), and after each trade; never pruned [§7]
- [ ] **PORT-03**: `GET /api/portfolio/history` returns at most the 1,000 most recent snapshots, oldest first [§8]
- [ ] **PORT-04**: User sees a positions table (ticker, qty, avg cost, current price, unrealized P&L, % change) [§10]
- [ ] **PORT-05**: User sees a portfolio heatmap (Recharts Treemap) sized by market value, colored red (≤−5%) → gray (0%) → green (≥+5%) by P&L %, labeled with ticker and P&L % (ticker only when small) [§10 Heatmap Colors]
- [ ] **PORT-06**: User sees a P&L line chart (Lightweight Charts) of total portfolio value from snapshots [§10]

### AI Chat (CHAT)

- [ ] **CHAT-01**: User can send a chat message via `POST /api/chat` and receive the assistant reply with per-action outcomes (`executed`/`failed` + `error`) in the specified response shape [§8, §9]
- [ ] **CHAT-02**: The backend builds the prompt from a system prompt ("trading_workstation, an AI trading assistant" with the §9 guidance), live portfolio + watchlist context, and the last 20 messages with prior action outcomes summarized [§9 How It Works]
- [ ] **CHAT-03**: The LLM is called via LiteLLM `acompletion` → OpenRouter `openrouter/openai/gpt-oss-120b` with Cerebras provider, using the `cerebras-inference` skill, requesting structured output and validating with Pydantic `model_validate_json` (all fields required, `Literal` enums) [§9]
- [ ] **CHAT-04**: Watchlist changes then trades from the LLM response auto-execute through the same validation as manual actions; each action succeeds or fails independently [§9 Auto-Execution, §8 Chat ordering]
- [ ] **CHAT-05**: LLM failure, 30s timeout or schema mismatch returns 200 with `"Sorry, I couldn't process that request. Please try again."` and no actions; no retries; both messages stored [§9 Failure Handling]
- [ ] **CHAT-06**: Without `OPENROUTER_API_KEY` (and no mock) the app still starts with a warning, and chat returns `"The AI assistant isn't configured. Set OPENROUTER_API_KEY in .env and restart."` without calling the LLM [§5]
- [ ] **CHAT-07**: With `LLM_MOCK=true`, deterministic mock rules (buy/sell/add/remove/fail/default) replace only the LLM call and flow through the real execution and persistence path [§9 LLM Mock Mode]
- [ ] **CHAT-08**: User and assistant messages persist in `chat_messages`; `GET /api/chat/history` returns the last 50, oldest first [§8]
- [ ] **CHAT-09**: User sees a docked/collapsible chat panel with scrolling history (restored on reload), a welcome message with example prompts when empty, a typing indicator with input disabled while waiting, and executed/failed actions rendered inline [§10]
- [ ] **CHAT-10**: After a chat response with executed actions, the frontend refetches the portfolio (and the watchlist for watchlist changes) [§10 Header Values]

### Terminal UI (UI)

- [ ] **UI-01**: Next.js + TypeScript app in `frontend/` builds as a static export (`output: 'export'`, `images.unoptimized`) styled with Tailwind using the custom dark theme and brand colors [§2, §10, §11]
- [ ] **UI-02**: A single SSE hook uses `EventSource` on `/api/stream/prices`, keeps capped per-ticker history buffers (~1,000 points, appending only on timestamp change), and drives all live price displays [§10 Technical Notes]
- [ ] **UI-03**: User sees a connection status dot: green (open and event within 5s), yellow (connecting, or open but stale >5s), red (closed); the frontend recreates the `EventSource` every 5s when closed [§10 Connection Status]
- [ ] **UI-04**: User sees a header with live total portfolio value (cash + Σ qty × latest SSE price, falling back to `current_price`) and cash balance [§10 Header Values]
- [ ] **UI-05**: User can click a watchlist ticker to show a larger Lightweight Charts price chart; the first watchlist ticker is auto-selected on load [§2, §10]
- [ ] **UI-06**: Every element shows the specified empty/loading states (empty watchlist, no price `—`, "Select a ticker", "Waiting for price data…", no positions, "Collecting portfolio history…") [§10 Empty & Loading States]
- [ ] **UI-07**: Layout is a dense, professional terminal that is desktop-first and functional on tablet widths [§2 Visual Design]

### Deployment (DEPLOY)

- [ ] **DEPLOY-01**: A multi-stage `Dockerfile` (Node 20 slim builds the frontend; Python 3.12 slim + uv runs the backend with the static build) exposes port 8000 and sets `DB_PATH=/app/db/trading_workstation.db` [§11]
- [ ] **DEPLOY-02**: User can run `docker run -v trading-workstation-data:/app/db -p 8000:8000 --env-file .env trading-workstation` and data persists across container restarts [§11 Docker Volume]
- [ ] **DEPLOY-03**: User can start/stop the app idempotently with `scripts/start_mac.sh` / `stop_mac.sh` and `scripts/start_windows.ps1` / `stop_windows.ps1` (build if needed or with `--build`, print URL, optionally open browser; stop never removes the volume) [§11]
- [ ] **DEPLOY-04**: `.gitignore` excludes `.env` and the SQLite DB file; `db/.gitkeep` exists; README quick start and test commands work as written [§4, planning/REVIEW.md]

### Testing (TEST)

- [ ] **TEST-01**: Backend pytest suite covers market data (simulator validity, GBM math, Massive parsing, interface conformance), trading logic and edge cases, LLM parsing/failure handling/mock, and API status codes and shapes [§12]
- [ ] **TEST-02**: Frontend Vitest + RTL suite covers price flash, the SSE hook (parsing, capped buffers, staleness status), live portfolio calculation, heatmap color scale and chat action rendering [§12]
- [ ] **TEST-03**: `test/docker-compose.test.yml` runs the app (`LLM_MOCK=true`) plus a version-matched Playwright container; tests read `BASE_URL` (default `http://localhost:8000`) [§12]
- [ ] **TEST-04**: E2E scenarios pass: fresh start, add/remove ticker, buy, sell, portfolio visualizations, mocked AI chat trade, SSE reconnection [§12 Key Scenarios]

## v2 Requirements

Deferred. Tracked but not in the current roadmap.

### Deployment

- **CLOUD-01**: Terraform configuration for AWS App Runner in `deploy/` [§11 Optional Cloud Deployment]

### Multi-user

- **MULTI-01**: Multiple user profiles using the existing `user_id` columns

## Out of Scope

| Feature | Reason |
|---------|--------|
| Authentication / login | Single-user simulated app; no login by design [§2] |
| Limit/stop orders, order book, partial fills, fees | Market orders only to keep portfolio math simple [§3] |
| Realized P&L | Not tracked per spec [§8] |
| Server-side price history | Charts accumulate on the frontend since page load [§6] |
| WebSockets | SSE covers one-way push [§3] |
| LLM token streaming | Cerebras is fast enough; a loading indicator suffices [§9] |
| Trade confirmation dialogs | Auto-execution is a deliberate demo choice [§9] |
| Root production `docker-compose.yml` | Start/stop scripts cover it [§13.8] |
| Second LLM call after failed actions | Outcomes are returned per action instead [§9] |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 1 | Pending |
| FND-02 | Phase 1 | Pending |
| FND-03 | Phase 1 | Pending |
| FND-04 | Phase 1 | Pending |
| FND-05 | Phase 1 | Pending |
| FND-06 | Phase 1 | Pending |
| FND-07 | Phase 1 | Pending |
| MKT-01 | Phase 1 | Pending |
| MKT-02 | Phase 2 | Pending |
| MKT-03 | Phase 1 | Pending |
| MKT-04 | Phase 2 | Pending |
| MKT-05 | Phase 2 | Pending |
| MKT-06 | Phase 2 | Pending |
| MKT-07 | Phase 1 | Pending |
| WATCH-01 | Phase 1 | Pending |
| WATCH-02 | Phase 2 | Pending |
| WATCH-03 | Phase 2 | Pending |
| WATCH-04 | Phase 1 | Pending |
| WATCH-05 | Phase 2 | Pending |
| TRADE-01 | Phase 3 | Pending |
| TRADE-02 | Phase 3 | Pending |
| TRADE-03 | Phase 3 | Pending |
| TRADE-04 | Phase 3 | Pending |
| TRADE-05 | Phase 3 | Pending |
| TRADE-06 | Phase 3 | Pending |
| TRADE-07 | Phase 3 | Pending |
| PORT-01 | Phase 3 | Pending |
| PORT-02 | Phase 3 | Pending |
| PORT-03 | Phase 5 | Pending |
| PORT-04 | Phase 3 | Pending |
| PORT-05 | Phase 5 | Pending |
| PORT-06 | Phase 5 | Pending |
| CHAT-01 | Phase 4 | Pending |
| CHAT-02 | Phase 4 | Pending |
| CHAT-03 | Phase 4 | Pending |
| CHAT-04 | Phase 4 | Pending |
| CHAT-05 | Phase 4 | Pending |
| CHAT-06 | Phase 4 | Pending |
| CHAT-07 | Phase 4 | Pending |
| CHAT-08 | Phase 4 | Pending |
| CHAT-09 | Phase 4 | Pending |
| CHAT-10 | Phase 4 | Pending |
| UI-01 | Phase 1 | Pending |
| UI-02 | Phase 1 | Pending |
| UI-03 | Phase 1 | Pending |
| UI-04 | Phase 3 | Pending |
| UI-05 | Phase 2 | Pending |
| UI-06 | Phase 5 | Pending |
| UI-07 | Phase 5 | Pending |
| DEPLOY-01 | Phase 6 | Pending |
| DEPLOY-02 | Phase 6 | Pending |
| DEPLOY-03 | Phase 6 | Pending |
| DEPLOY-04 | Phase 6 | Pending |
| TEST-01 | Phase 6 | Pending |
| TEST-02 | Phase 6 | Pending |
| TEST-03 | Phase 6 | Pending |
| TEST-04 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 57 total
- Mapped to phases: 57
- Unmapped: 0 ✓

---
*Requirements defined: 2026-11-03*
*Last updated: 2026-11-03 after roadmap creation (traceability mapped)*
