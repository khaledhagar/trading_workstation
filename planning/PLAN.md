# trading_workstation — AI Trading Workstation

## Project Specification

## 1. Vision

trading_workstation is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, % change
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (volume-mounted)               │
│  Background task: market data polling/sim        │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/trading_workstation.db`, volume-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real data via Massive API if key provided

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no docker-compose for production, no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |

---

## 4. Directory Structure

```
Trading_Workstation/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── db/                   # Schema definitions, seed data, migration logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # SQLite file location for local (non-Docker) runs
│   └── .gitkeep              # Directory exists in repo; trading_workstation.db is gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions and seed logic. The backend initializes the database at application startup — creating tables and seeding default data if the SQLite file doesn't exist or is empty (see §7).
- **`db/`** at the top level is where the SQLite file (`db/trading_workstation.db`) is created when the backend runs locally, outside Docker. In Docker, the database lives in the named volume `trading-workstation-data` mounted at `/app/db` (see §11), not in this directory.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required: OpenRouter API key for LLM chat functionality
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Massive (Polygon.io) API key for real market data
# If not set, the built-in market simulator is used (recommended for most users)
MASSIVE_API_KEY=

# Optional (only used with MASSIVE_API_KEY): force the Massive mode instead of auto-detecting the plan.
# "snapshot" = paid plans (live/delayed prices), "eod" = free plan (end-of-day prices). Empty = auto-detect
MASSIVE_MODE=

# Optional (only used in snapshot mode): seconds between Massive polls. Default 15, minimum 2
MASSIVE_POLL_INTERVAL=

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false

# Optional: SQLite file location. Default: <project root>/db/trading_workstation.db
# (project root = the parent directory of backend/). The Dockerfile sets it to /app/db/trading_workstation.db
DB_PATH=
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- `MASSIVE_MODE` and `MASSIVE_POLL_INTERVAL` are ignored without a Massive key. Invalid values are logged and replaced by the defaults; a `MASSIVE_POLL_INTERVAL` below the minimum is logged and raised to 2
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- **In Docker**, variables are passed with `docker run --env-file .env`; no `.env` file is copied into the image
- **Locally**, at startup the backend calls `python-dotenv`'s `load_dotenv(<project root>/.env)`, where project root is the parent of `backend/`, resolved from the code's location rather than the working directory. It does not override variables already set in the environment, so the same code works in both cases
- **Missing `OPENROUTER_API_KEY`** (and `LLM_MOCK` not `true`): the app still starts and logs a warning, and everything except chat works. `POST /api/chat` returns 200 with the assistant message `"The AI assistant isn't configured. Set OPENROUTER_API_KEY in .env and restart."` and no actions, and the LLM is not called

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface. The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

A summary of the market data design and its key data is in [`MARKET_DATA_SUMMARY.md`](MARKET_DATA_SUMMARY.md). The full implementation design, with code for every module, is archived in [`archive/MARKET_DATA_DESIGN.md`](archive/MARKET_DATA_DESIGN.md).

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., tech stocks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic seed prices (e.g., AAPL ~$190, GOOGL ~$175, etc.)
- Runs as an in-process background task — no external dependencies
- **Unknown tickers**: any ticker that passes format validation (see Ticker Rules) is accepted. Tickers without a predefined seed get a random seed price between $50 and $300 and default volatility, and are uncorrelated with the rest of the market
- **Reference price** (the baseline for change %): the seed price, i.e. the ticker's first price since server start

### Massive API (Optional)

- REST API polling (not WebSocket) — simpler, works on all tiers
- The plan tier decides what's available: the live snapshot endpoint is **not on the free plan** (see `MASSIVE_API.md` §1). The backend therefore runs in one of two modes, detected automatically from the first response (a 403 on the snapshot endpoint means the free plan), or forced with `MASSIVE_MODE`:

| Mode | Plans | How | Interval |
|---|---|---|---|
| `snapshot` | Starter and above | **One call per poll** for all tracked tickers, regardless of count: `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...` | `MASSIVE_POLL_INTERVAL` (default 15 s). Paid plans have no rate limit |
| `eod` | Basic (free, 5 calls/min) | End-of-day prices from the Daily Market Summary (`GET /v2/aggs/grouped/locale/us/market/stocks/{date}`), which returns every US stock in one call. Loads the last two trading days | Refreshed every 30 min, with calls spaced ≥ 12 s apart |

- **Snapshot mode parsing**: price = the first value ≥ $0.01 of `lastTrade.p` → `min.c` → `day.c` → `prevDay.c`; **reference price** = `prevDay.c` (previous close)
- **EOD mode parsing**: price = the latest trading day's close; **reference price** = the close of the trading day before. Prices don't move during the day, so SSE events report `direction: "flat"`, except for up to one refresh (30 min) after a new trading day is loaded, when `direction` shows the move from the previous day. The simulator remains the default and the better demo
- **Unknown tickers**: in snapshot mode, adding a ticker makes one snapshot call for it; in EOD mode it's looked up in the already-loaded whole-market data (no call). If Massive has no data for it, or its price is below one cent (it would round to $0.00), the add is rejected with 400 `"Unknown ticker: XYZ"`
- **Provider unavailable**: if Massive is down, rate-limited, still loading its first data at startup (up to ~20 s), or resetting its snapshots (3:30–4:00 AM ET, when every price field is zero), an add fails with 503 (see §8 Errors). The background poller keeps the last known prices and retries on its next cycle

### Ticker Rules

- Input is trimmed and uppercased, then must match `^[A-Z][A-Z.]{0,9}$` (e.g. `AAPL`, `BRK.B`); otherwise 400 `"Invalid ticker"`
- The same rules apply to manual input and to LLM-issued actions

### Tracked Tickers

- The set of tickers the market data source prices and the SSE stream emits is **watchlist ∪ tickers with an open position**
- Removing a held ticker from the watchlist therefore does not stop its price updates, so the position stays valued; it only disappears from the watchlist panel
- Selling a position to zero for a ticker that isn't watched removes it from the tracked set
- When a ticker is added, the source **seeds the cache immediately**: the simulator with its seed price, and Massive with the price from the validation snapshot call (snapshot mode) or the loaded end-of-day data (EOD mode). A trade right after an add therefore always has a price
- Defensive fallback: a trade on a ticker with no price in the cache is rejected with 400 `"No price available for XYZ yet"`

### Shared Price Cache

- A single background task (simulator or Massive poller) writes to an in-memory price cache
- The cache holds the latest price, previous price, reference price, and timestamp for each ticker
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- Server pushes price updates for all tracked tickers (see Tracked Tickers) at a regular cadence (~500ms)
- Each SSE event contains ticker, price, previous price, timestamp, change direction, and change % versus the reference price
- Client handles reconnection automatically (EventSource has built-in retry)

**Event format** — one unnamed event (default `message` type) per tick, whose `data` is a JSON object keyed by ticker containing every tracked ticker:

```text
data: {"AAPL": {"ticker": "AAPL", "price": 190.12, "previous_price": 190.05, "timestamp": "2026-01-01T12:00:00.500Z", "direction": "up", "change_percent": 0.48}, "MSFT": {...}}
```

- `direction` is one of `"up"`, `"down"`, `"flat"` (price vs. previous price)
- `change_percent` = `(price − reference_price) / reference_price × 100`, rounded to 2 decimals. This is the value the watchlist shows as "daily change %"
- Tickers with no price yet are omitted from the event

### Price History (Charts)

- There is **no server-side price history**. Sparklines and the main chart are both built on the frontend from SSE events received since page load, so they start empty and fill in progressively
- The frontend keeps a capped buffer per ticker (e.g. the last 1,000 points) so memory stays bounded

---

## 7. Database

### SQLite with Automatic Initialization

The backend initializes the database **once at application startup**, in the FastAPI lifespan handler, before the market data task starts or any request is served. It never initializes on first request, so concurrent first requests can't race each other. At startup it:

1. Resolves the file path from `DB_PATH` (see §5) and creates the parent directory if it's missing
2. Enables WAL mode
3. Runs the schema with `CREATE TABLE IF NOT EXISTS` for every table, so it is idempotent and safe on every boot
4. Seeds default data **only if `users_profile` has no `"default"` row**, so an existing user's data is never overwritten, even if they have emptied their watchlist

This means:

- No separate migration step
- No manual database setup
- Fresh Docker volumes start with a clean, seeded database automatically
- Deleting `trading_workstation.db` and restarting gives a clean reset

### Schema

All tables except `users_profile` include a `user_id` column defaulting to `"default"`. In `users_profile`, the primary key `id` *is* the user id, and the other tables' `user_id` refers to it. This is hardcoded for now (single-user) but enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- PRIMARY KEY `(user_id, ticker)`, a composite key with no surrogate `id`, since a row is fully identified by user and ticker

**positions** — Current holdings (one row per ticker per user)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT (ISO timestamp)
- PRIMARY KEY `(user_id, ticker)`. Upserts use `INSERT … ON CONFLICT(user_id, ticker) DO UPDATE`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded at startup, every 30 seconds by a background task (including when there are no positions), and immediately after each trade execution. Rows are never pruned (~2,880 rows/day is negligible for SQLite); the history endpoint limits what it returns instead.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — trades executed, watchlist changes made; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

---

## 8. API Endpoints

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive complete JSON response (message + executed actions) |
| GET | `/api/chat/history` | Recent chat messages (oldest first), so the chat panel survives a page reload |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) |

### Conventions

- All request and response bodies are JSON; all timestamps are ISO 8601 UTC with a `Z` suffix. **Price timestamps** (SSE events and `GET /api/watchlist`) include milliseconds, e.g. `"2026-01-01T12:00:00.500Z"`, because the simulator ticks every 500 ms and whole seconds would make consecutive ticks collide. Other timestamps may use whole seconds (e.g. `"2026-01-01T12:00:00Z"`); clients must accept both
- Tickers are normalized to uppercase by the backend
- Monetary values are returned as numbers rounded to 2 decimals; percentages as numbers (e.g. `2.5` means 2.5%)

### Errors

All errors use FastAPI's default shape: `{"detail": "Insufficient cash: need $1,901.20, have $500.00"}`. `detail` is a human-readable message the frontend can display as-is.

| Status | When |
|--------|------|
| 400 | Business-rule failure: insufficient cash, insufficient shares, unknown/unpriced ticker |
| 404 | `DELETE /api/watchlist/{ticker}` for a ticker not in the watchlist |
| 422 | Malformed request body (FastAPI/Pydantic validation, e.g. missing field, quantity ≤ 0) |
| 500 | Unexpected server error |
| 503 | The market data provider (Massive) can't answer right now: down, rate-limited, or still loading at startup. `detail` is always `"Market data unavailable, try again shortly"`; the provider's error stays in the server log. Never returned by the simulator |

### Trading Rules

These rules apply identically to trade-bar trades and LLM-issued trades.

- **Quantity**: must be > 0. Fractional shares are allowed from both the trade bar and the LLM, with up to 4 decimal places (more precision → 422)
- **Fill price**: the current price in the cache at execution time
- **Buy**: requires `cash_balance ≥ quantity × price`, otherwise 400 `"Insufficient cash: need $X, have $Y"`. The new `avg_cost` is the weighted average: `(old_qty × old_avg + qty × price) / (old_qty + qty)`
- **Sell**: requires `held quantity ≥ quantity`, otherwise 400 `"Insufficient shares: have X, tried to sell Y"`. `avg_cost` is unchanged by sells. Realized P&L is not tracked
- **Full exit**: if the remaining quantity is below `0.00005` (float tolerance), the `positions` row is **deleted**. A later buy starts a fresh position with a fresh `avg_cost`
- **Rounding**: `cash_balance` is rounded to 2 decimals after every trade; quantities are rounded to 4 decimals
- **Unwatched tickers**: buying a ticker that isn't in the watchlist **auto-adds it to the watchlist first** (same validation and cache seeding as `POST /api/watchlist`), then executes the buy. The frontend refetches `/api/watchlist` after a trade when the ticker isn't already in its local list. Selling a ticker you don't hold fails with the insufficient-shares error
- **Chat ordering**: in a chat response, `watchlist_changes` are applied before `trades`

### Persistence & Concurrency

- Each trade is **one SQLite transaction**, started with `BEGIN IMMEDIATE`: read cash and position → validate → update cash → upsert/delete position → insert trade → insert snapshot. Either everything commits or nothing does
- `BEGIN IMMEDIATE` takes the write lock before validation, so concurrent trades (e.g. a manual trade and an LLM trade at the same time) cannot both pass validation against stale balances
- The database runs in WAL mode with `busy_timeout = 5000` ms; each request and the snapshot task use their own short-lived connection
- **`GET /api/portfolio/history`** returns at most the most recent **1,000** snapshots (~8 hours at 30s intervals), oldest first

### Response Contracts

**`GET /api/portfolio`** → 200

```json
{
  "cash_balance": 8098.80,
  "positions_value": 1905.00,
  "total_value": 10003.80,
  "unrealized_pnl": 3.80,
  "positions": [
    {
      "ticker": "AAPL",
      "quantity": 10,
      "avg_cost": 190.12,
      "current_price": 190.50,
      "market_value": 1905.00,
      "unrealized_pnl": 3.80,
      "pnl_percent": 0.20
    }
  ]
}
```

**`POST /api/portfolio/trade`** — request `{"ticker": "AAPL", "quantity": 10, "side": "buy"}` → 200 with the executed trade plus the updated portfolio (same shape as `GET /api/portfolio`), so the frontend needs no follow-up fetch:

```json
{
  "trade": {"id": "uuid", "ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.12, "executed_at": "2026-01-01T12:00:00Z"},
  "portfolio": { "...": "same shape as GET /api/portfolio" }
}
```

**`GET /api/portfolio/history`** → 200, oldest first:

```json
[{"total_value": 10000.00, "recorded_at": "2026-01-01T12:00:00Z"}]
```

**`GET /api/watchlist`** → 200. `price`, `previous_price`, `direction`, `change_percent` and `timestamp` are `null` if the ticker has no price yet:

```json
[{"ticker": "AAPL", "price": 190.12, "previous_price": 190.05, "direction": "up", "change_percent": 0.48, "timestamp": "2026-01-01T12:00:00Z"}]
```

**`POST /api/watchlist`** — request `{"ticker": "PYPL"}` → 200 with the full updated watchlist (same shape as `GET /api/watchlist`). Adding a ticker that is already watched is idempotent (200, no error).

**`DELETE /api/watchlist/{ticker}`** → 200 with the full updated watchlist.

**`POST /api/chat`** — request `{"message": "Buy 10 AAPL"}` → 200. Every requested action is reported with its outcome; failed actions carry an `error` and are shown inline by the frontend (no second LLM call):

```json
{
  "id": "uuid",
  "role": "assistant",
  "content": "Done — bought 10 AAPL at $190.12.",
  "actions": {
    "trades": [
      {"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed", "price": 190.12, "error": null}
    ],
    "watchlist_changes": [
      {"ticker": "PYPL", "action": "add", "status": "failed", "error": "Unknown ticker"}
    ]
  },
  "created_at": "2026-01-01T12:00:00Z"
}
```

**`GET /api/chat/history`** → 200, the most recent 50 messages, oldest first. Each item has the same shape as the `POST /api/chat` response; `actions` is `null` for user messages.

**`GET /api/health`** → 200 `{"status": "ok"}`

---

## 9. LLM Integration

When writing code to make calls to LLMs, use the `cerebras-inference` skill (`.claude/skills/cerebras/SKILL.md`) to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

The skill's snippets use the synchronous `completion`. Inside FastAPI's async routes, use LiteLLM's `acompletion` with the same arguments, so the event loop (and with it the SSE streams) is not blocked while waiting for the LLM.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads recent conversation history from the `chat_messages` table: the **last 20 messages**, oldest first. Each prior assistant message's `actions` are appended to its content as a compact outcome summary (e.g. `[Actions: buy 10 AAPL @ 190.12 executed; add PYPL failed: Unknown ticker]`), so the LLM knows what actually happened
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM via LiteLLM → OpenRouter, requesting structured output, using the cerebras-inference skill
5. Parses the complete structured JSON response by validating it against the Pydantic model with `model_validate_json`
6. Auto-executes any watchlist changes, then any trades, specified in the response (see Trading Rules in §8), recording each action's outcome
7. Stores the user message, then the assistant message with its action outcomes, in `chat_messages`
8. Returns the complete JSON response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

### Structured Output Schema

The LLM is instructed to respond with JSON matching this schema:

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (required, may be empty `[]`): Array of trades to auto-execute. Each trade goes through the same validation as manual trades (sufficient cash for buys, sufficient shares for sells). `side` is `"buy"` or `"sell"`; `quantity` is a number > 0
- `watchlist_changes` (required, may be empty `[]`): Array of watchlist modifications. `action` is `"add"` or `"remove"`

All fields are **required**, and the arrays are empty when there is nothing to do. Strict structured-output modes need every property listed as required, and it also spares the backend from handling missing keys. Use `Literal` types in the Pydantic model for `side` and `action` so they become enums in the schema.

### Failure Handling

- **The LLM call fails** (network error, timeout after 30s, provider error), **or the response doesn't validate** against the schema: return **200** with a normal chat response whose `content` is `"Sorry, I couldn't process that request. Please try again."` and whose action arrays are empty. Both the user message and this assistant message are stored. The error is logged server-side and not exposed to the user
- No retries: the user can simply resend
- A single invalid action (e.g. an unknown ticker) does not affect the other actions in the same response. Each one is executed and reported independently

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

If a trade or watchlist change fails validation (e.g., insufficient cash), the LLM is **not** called again. Instead, each action's outcome (`executed`/`failed` + `error`) is returned alongside the LLM's message (see the `POST /api/chat` contract in §8), and the frontend renders failed actions inline with a clear error style. The system prompt tells the LLM to phrase trade confirmations as intent ("Placing an order to buy 10 AAPL…") rather than claiming success, because it writes its message before execution. On the next turn it sees the real outcomes via the history summary.

### System Prompt Guidance

The LLM should be prompted as "trading_workstation, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON
- Phrase trades and watchlist changes as actions being taken, not as confirmed results (outcomes are shown to the user separately)
- Only include trades the user explicitly asked for or agreed to. Suggestions go in `message`, not in `trades`

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling OpenRouter. This enables:
- Fast, free, reproducible E2E tests
- Development without an API key
- CI/CD pipelines

The mock replaces **only the LLM call**. Its output goes through the same parsing, action execution, persistence and response path as a real response. Rules (case-insensitive, checked in order, first match wins):

| User message matches | Mock structured response |
|---|---|
| `buy <qty> <TICKER>` (e.g. "buy 5 AAPL") | `message: "Buying <qty> <TICKER>."`, one buy trade |
| `sell <qty> <TICKER>` | `message: "Selling <qty> <TICKER>."`, one sell trade |
| `add <TICKER>` | `message: "Adding <TICKER> to your watchlist."`, one add change |
| `remove <TICKER>` | `message: "Removing <TICKER> from your watchlist."`, one remove change |
| `fail` | Simulates an LLM failure, which exercises the Failure Handling path |
| anything else | `message: "This is a mock response from trading_workstation."`, no actions |

`<qty>` matches `\d+(\.\d+)?` and `<TICKER>` matches `[A-Za-z.]+`. The pattern may appear anywhere in the message.

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), daily change %, and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, using data from `portfolio_snapshots`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, % change
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history, loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Charting libraries, one per job:
  - **Main price chart and P&L chart**: TradingView **Lightweight Charts** (canvas, built for streaming financial series). Check its current docs, since the series API changed between major versions, and keep its default attribution enabled (license requirement)
  - **Sparklines**: a small hand-rolled inline SVG `<polyline>` component, with no library. A full chart instance per watchlist row is needless overhead
  - **Portfolio heatmap**: Recharts `Treemap` with a custom content renderer for the colors and labels. Recharts renders SVG, which is fine for a handful of rectangles
- Price flash effect: when a ticker's `price` differs from the last value the frontend saw for it, briefly apply a CSS class with background color transition, then remove it. Compare prices rather than relying on `direction` alone: with Massive, the same entry (and the same `direction`) is re-sent every 500 ms until the next poll
- Price history buffers (sparklines, main chart): append a point **only when a ticker's `timestamp` changes**, otherwise one 15-second Massive poll becomes 30 identical points. For Lightweight Charts, convert with `Date.parse(timestamp) / 1000` and drop any point whose time isn't greater than the previous one (the library requires strictly increasing times)
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

### Connection Status

`EventSource.readyState` only has `CONNECTING`, `OPEN` and `CLOSED`, so the indicator combines it with how recently data arrived:

| Dot | Condition |
|-----|-----------|
| 🟢 Green (connected) | `OPEN` and an event arrived within the last 5 seconds |
| 🟡 Yellow (reconnecting) | `CONNECTING` (initial connect or automatic retry after an error), **or** `OPEN` but no event for more than 5 seconds |
| 🔴 Red (disconnected) | `CLOSED`, meaning the browser has given up (e.g. an HTTP error response) |

When the state is `CLOSED`, the frontend creates a new `EventSource` every 5 seconds until it connects again. A 1-second interval timer re-evaluates staleness.

### Header Values

- **Cash balance** comes from the last `GET /api/portfolio` response (or the portfolio embedded in a trade response)
- **Total portfolio value** is computed **on the frontend**: `cash + Σ(position quantity × latest SSE price)`, falling back to the position's `current_price` from the portfolio response until an SSE price arrives. It updates on every SSE event without extra requests
- The frontend refetches `/api/portfolio` on page load, after each manual trade (or uses the embedded portfolio), and after every chat response that contains at least one executed action. It also refetches `/api/watchlist` after chat responses with executed watchlist changes

### Heatmap Colors

- Each rectangle is sized by `market_value` and colored by the position's `pnl_percent`
- The color scale runs from red (≤ −5%) through a neutral gray (0%) to green (≥ +5%), with intensity interpolated linearly and clamped at ±5%
- Labels show the ticker and `pnl_percent`; small rectangles show the ticker only

### Empty & Loading States

| Element | State | Display |
|---------|-------|---------|
| Watchlist | No tickers | "Your watchlist is empty — add a ticker above or ask trading_workstation" |
| Watchlist row | No price yet | Price shows `—`, sparkline area blank |
| Main chart | No ticker selected | Auto-select the first watchlist ticker on load; if the watchlist is empty, show "Select a ticker" |
| Main chart | Selected, fewer than 2 points | "Waiting for price data…" |
| Heatmap | No positions | "No positions yet — buy shares with the trade bar or ask trading_workstation" |
| Positions table | No positions | A single row with the same message |
| P&L chart | Fewer than 2 snapshots | "Collecting portfolio history…" (a snapshot is recorded at startup and every 30s, so this resolves quickly) |
| Chat | No history | A frontend-only welcome message with 2–3 example prompts (not stored in the DB) |
| Chat | Waiting for response | Animated typing indicator; input and send button disabled |

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Set ENV DB_PATH=/app/db/trading_workstation.db
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000.

### Static File Serving

- All `/api/*` routers are registered **first**. The static export is mounted **last**, with `app.mount("/", StaticFiles(directory=<static dir>, html=True))`, so API routes always take precedence and `/` serves `index.html`
- The app is a single page (`index.html`), so there is no client-side routing to fall back for and no `trailingSlash` concerns
- Next.js config: `output: 'export'` and `images: { unoptimized: true }` (the default image optimizer isn't available in static export)
- If the static directory doesn't exist (e.g. running the backend locally without a frontend build), the backend skips the mount and logs a notice, so the API still works

### Docker Volume

The SQLite database persists via a named Docker volume:

```bash
docker run -v trading-workstation-data:/app/db -p 8000:8000 --env-file .env trading-workstation
```

This is a **named volume, not a bind mount**: `trading-workstation-data` is managed by Docker and mounted at `/app/db`, where the backend writes `trading_workstation.db`. The project's top-level `db/` directory is **not** mounted into the container. A named volume avoids host-path problems (spaces in paths, Windows path translation) and keeps a live SQLite file out of synced folders such as OneDrive. To reset the data, run `docker volume rm trading-workstation-data` while the container is stopped.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume mount, port mapping, and `.env` file
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

### Optional Cloud Deployment

The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory as a stretch goal, but is not part of the core build.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: simulator generates valid prices, GBM math is correct, Massive API response parsing works, both implementations conform to the abstract interface
- Portfolio: trade execution logic, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow
- API routes: correct status codes, response shapes, error handling

**Frontend (Vitest + React Testing Library)** — limited to logic-heavy units; rendering and CRUD flows are covered by E2E tests, not duplicated here:
- Price flash: the flash class is applied on up/down changes and removed afterwards
- SSE hook: parses events, maintains capped per-ticker history buffers, derives connection status (including the 5s staleness rule)
- Portfolio calculations: live total value from cash + positions + SSE prices, with fallback to `current_price`
- Heatmap color scale: the ±5% clamped red–gray–green mapping
- Chat action rendering: executed vs. failed action outcomes display correctly

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container (official `mcr.microsoft.com/playwright` image, version-matched to the `@playwright/test` package). This keeps browser dependencies out of the production image and makes runs reproducible across machines. The tests read the app URL from a `BASE_URL` env var (compose sets it to the app service; default `http://localhost:8000`), so developers can also run `npx playwright test` from the host against a running container for faster iteration.

**Environment**: Tests run with `LLM_MOCK=true` by default for speed and determinism.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message, receive a response, trade execution appears inline
- SSE resilience: disconnect and verify reconnection

---

## 13. Review Log

The resolved review questions from documentation review are in [`archive/PLAN_REVIEW.md`](archive/PLAN_REVIEW.md). Every outcome is already reflected in this spec.
