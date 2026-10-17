# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

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

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false

# Optional: SQLite file location. Default: <project root>/db/trading_workstation.db
# (project root = the parent directory of backend/). The Dockerfile sets it to /app/db/trading_workstation.db
DB_PATH=
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- **In Docker**, variables are passed with `docker run --env-file .env`; no `.env` file is copied into the image
- **Locally**, at startup the backend calls `python-dotenv`'s `load_dotenv(<project root>/.env)`, where project root is the parent of `backend/`, resolved from the code's location rather than the working directory. It does not override variables already set in the environment, so the same code works in both cases
- **Missing `OPENROUTER_API_KEY`** (and `LLM_MOCK` not `true`): the app still starts and logs a warning, and everything except chat works. `POST /api/chat` returns 200 with the assistant message `"The AI assistant isn't configured. Set OPENROUTER_API_KEY in .env and restart."` and no actions, and the LLM is not called

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface. The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

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
- Polls for the tracked ticker set (see Tracked Tickers) on a configurable interval
- **One call per poll**, regardless of ticker count, via the multi-ticker snapshot endpoint: `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...`. This is what makes the free tier viable
- Free tier (5 calls/min): poll every 15 seconds
- Paid tiers: poll every 2-15 seconds depending on tier
- Parses REST response into the same format as the simulator: price = `lastTrade.p` (falling back to `day.c` when absent), **reference price** = `prevDay.c` (previous close)
- **Unknown tickers**: when a ticker is added, the backend makes one snapshot call for that ticker. If Massive returns no data for it, the add is rejected with 400 `"Unknown ticker: XYZ"`

### Ticker Rules

- Input is trimmed and uppercased, then must match `^[A-Z][A-Z.]{0,9}$` (e.g. `AAPL`, `BRK.B`); otherwise 400 `"Invalid ticker"`
- The same rules apply to manual input and to LLM-issued actions

### Tracked Tickers

- The set of tickers the market data source prices and the SSE stream emits is **watchlist ∪ tickers with an open position**
- Removing a held ticker from the watchlist therefore does not stop its price updates, so the position stays valued; it only disappears from the watchlist panel
- Selling a position to zero for a ticker that isn't watched removes it from the tracked set
- When a ticker is added, the source **seeds the cache immediately**: the simulator with its seed price, and Massive with the price from the validation snapshot call. A trade right after an add therefore always has a price
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
data: {"AAPL": {"ticker": "AAPL", "price": 190.12, "previous_price": 190.05, "timestamp": "2026-01-01T12:00:00Z", "direction": "up", "change_percent": 0.48}, "MSFT": {...}}
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

- All request and response bodies are JSON; all timestamps are ISO 8601 UTC with a `Z` suffix (e.g. `"2026-01-01T12:00:00Z"`)
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

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
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
| anything else | `message: "This is a mock response from FinAlly."`, no actions |

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
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
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
| Watchlist | No tickers | "Your watchlist is empty — add a ticker above or ask FinAlly" |
| Watchlist row | No price yet | Price shows `—`, sparkline area blank |
| Main chart | No ticker selected | Auto-select the first watchlist ticker on load; if the watchlist is empty, show "Select a ticker" |
| Main chart | Selected, fewer than 2 points | "Waiting for price data…" |
| Heatmap | No positions | "No positions yet — buy shares with the trade bar or ask FinAlly" |
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

## 13. Review: Questions, Clarifications & Simplification Opportunities

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
