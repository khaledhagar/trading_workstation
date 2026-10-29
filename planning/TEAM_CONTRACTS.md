# Team Contracts — internal interfaces between agents

PLAN.md is the product spec (external API, behaviour). This file fixes the **internal** seams so
agents can build in parallel. If you need to change a contract, message the owner and the team lead
(`main`) first; update this file when agreed.

## 1. File ownership

| Agent | Owns (writes) | Must not edit |
|---|---|---|
| `db-engineer` | `backend/db/**`, `backend/tests/db/**` | everything else |
| `backend-engineer` | `backend/app/main.py`, `backend/app/api/**` (except `chat.py`), `backend/app/services/**`, `backend/tests/api/**`, `backend/tests/services/**`, `backend/pyproject.toml` + `uv.lock` (others ask for deps) | `backend/app/market/**` (done; read-only) |
| `llm-engineer` | `backend/app/llm/**`, `backend/app/api/chat.py`, `backend/tests/llm/**` | |
| `frontend-engineer` | `frontend/**` | |
| `devops-engineer` | `Dockerfile`, `.dockerignore`, `.env.example`, `scripts/**`, `test/docker-compose.test.yml`, `.gitignore` | |
| `integration-tester` | `test/**` except `docker-compose.test.yml` (Playwright config, specs, `test/package.json`), `planning/E2E_ISSUES.md` | product code — report bugs to the owner instead |

`backend/app/market/` is complete (see `MARKET_DATA_SUMMARY.md`). Import only its public names.
Nobody commits to git; the team lead handles commits.

## 2. Database layer — `backend/db/` (package `db`, importable since pytest/uvicorn run with `backend/` on the path)

All functions are **synchronous** `sqlite3`; `user_id` defaults to `"default"` everywhere.

```python
# db/__init__.py re-exports these
def get_db_path() -> Path            # DB_PATH env or <project root>/db/trading_workstation.db
def init_db(path: Path | None = None) -> Path   # mkdir, WAL, schema (IF NOT EXISTS), seed if no "default" profile
def connect(path: Path | None = None) -> sqlite3.Connection
    # row_factory=sqlite3.Row, busy_timeout=5000, isolation_level=None (autocommit; explicit BEGIN IMMEDIATE for writes)
    # usable as a context manager that closes the connection

def tracked_tickers(conn, user_id="default") -> set[str]        # watchlist ∪ positions
def get_cash(conn, user_id="default") -> float
def list_positions(conn, user_id="default") -> list[dict]        # {ticker, quantity, avg_cost, updated_at}, ordered by ticker
def get_position(conn, ticker, user_id="default") -> dict | None

def list_watchlist(conn, user_id="default") -> list[str]         # ordered by added_at, then ticker
def add_watchlist(conn, ticker, user_id="default") -> bool       # True if inserted; ON CONFLICT DO NOTHING
def remove_watchlist(conn, ticker, user_id="default") -> bool    # False if it wasn't there

class TradeError(ValueError): ...   # str(exc) is the exact 400 detail from PLAN.md §8

def execute_trade(conn, *, ticker, side, quantity, get_price, user_id="default") -> dict
    # One BEGIN IMMEDIATE transaction (PLAN.md §8 Persistence): price = get_price(ticker) read INSIDE the tx
    # (None -> TradeError("No price available for XYZ yet")); validate cash/shares (exact messages, $ with
    # thousands separators and 2 dp e.g. "Insufficient cash: need $1,901.20, have $500.00",
    # "Insufficient shares: have 5, tried to sell 10" — quantities formatted without trailing zeros);
    # update cash (round 2), upsert/delete position (round qty 4, delete if < 0.00005), insert trade,
    # insert snapshot of total value = cash + Σ qty × (get_price(t) or avg_cost). Commit or rollback.
    # Returns the trade: {id, ticker, side, quantity, price, executed_at}

def insert_snapshot(conn, total_value, user_id="default") -> None
def list_snapshots(conn, limit=1000, user_id="default") -> list[dict]   # {total_value, recorded_at}, oldest first

def insert_chat_message(conn, role, content, actions: dict | None, user_id="default") -> dict
    # returns {id, role, content, actions (dict|None), created_at}
def list_chat_messages(conn, limit=50, user_id="default") -> list[dict]  # most recent `limit`, oldest first

def utc_now_iso() -> str   # "2026-01-01T12:00:00Z"
```

## 3. Services — `backend/app/services/` (backend-engineer)

Shared by REST routes and the chat flow, so manual and LLM actions behave identically.
`state` is `app.state` (has `.price_cache: PriceCache`, `.market: MarketDataSource`).

```python
# app/services/portfolio.py
def build_portfolio(conn, cache) -> dict          # exact GET /api/portfolio shape, values rounded 2 dp
                                                  # positions without a cached price use avg_cost
# app/services/watchlist.py
def watchlist_rows(conn, cache) -> list[dict]     # GET /api/watchlist shape
async def add_ticker(state, raw_ticker) -> list[dict]     # normalize → market.add_ticker → db insert → rows
async def remove_ticker(state, raw_ticker) -> list[dict]  # raises NotInWatchlistError (→404) ; then resync
async def resync_market(state) -> None            # market.sync_tickers(db.tracked_tickers(conn))
class NotInWatchlistError(LookupError)
# app/services/trading.py
async def trade(state, raw_ticker, side, quantity) -> dict   # {"trade": ..., "portfolio": ...}
    # normalize; buy of unwatched ticker → add_ticker first; db.execute_trade; resync after a sell
```

Errors raised from services and mapped by global handlers in `main.py`:
`InvalidTickerError`/`UnknownTickerError`/`TradeError` → 400, `NotInWatchlistError` → 404,
`MarketDataUnavailableError` → 503 `"Market data unavailable, try again shortly"`.
Chat code catches these per action and uses `str(exc)` as the action `error`.

Validation of `quantity` (> 0, ≤ 4 decimals → 422) lives in the Pydantic request model of the trade route;
the chat flow applies the same check itself and reports a failed action.

## 4. LLM — `backend/app/llm/` + `backend/app/api/chat.py` (llm-engineer)

```python
# app/llm/models.py
class TradeAction(BaseModel): ticker: str; side: Literal["buy","sell"]; quantity: float
class WatchlistChange(BaseModel): ticker: str; action: Literal["add","remove"]
class LLMResponse(BaseModel): message: str; trades: list[TradeAction]; watchlist_changes: list[WatchlistChange]
# app/llm/service.py
async def handle_chat(state, message: str) -> dict    # full POST /api/chat response; never raises for LLM failures
# app/api/chat.py
router = APIRouter(prefix="/api/chat")                # POST "" and GET "/history"
```

Env: `LLM_MOCK`, `OPENROUTER_API_KEY` read at call time (not import time) so tests can monkeypatch.

## 5. App wiring — `backend/app/main.py` (backend-engineer)

`app = FastAPI(lifespan=...)`; run with `cd backend && uv run uvicorn app.main:app --port 8000`.
Lifespan order per MARKET_DATA_SUMMARY §10. Routers: market stream, portfolio, watchlist, chat (import
`app.api.chat.router`), health; then static mount from `STATIC_DIR` env or `backend/static/` (skip if missing).
A test factory `create_app(...)` or fixtures that let tests use a temp `DB_PATH` and a fast simulator are encouraged.

## 6. Frontend ↔ E2E: stable `data-testid`s (frontend-engineer implements, integration-tester relies on)

| testid | Element |
|---|---|
| `connection-status` | header dot; attribute `data-status="connected|reconnecting|disconnected"` |
| `header-total-value`, `header-cash` | header values (text like `$10,000.00`) |
| `watchlist` | watchlist panel; `watchlist-empty` empty message |
| `watchlist-row-<TICKER>` | one row; inside: `price-<TICKER>`, `change-<TICKER>`, `sparkline-<TICKER>`, `remove-<TICKER>` button |
| `watchlist-add-input`, `watchlist-add-button` | add ticker form |
| `main-chart`, `main-chart-ticker` | selected-ticker chart and its title |
| `trade-ticker`, `trade-quantity`, `trade-buy`, `trade-sell`, `trade-error` | trade bar |
| `positions-table`, `position-row-<TICKER>` (cells `position-qty-<TICKER>`, `position-pnl-<TICKER>`), `positions-empty` | positions |
| `heatmap`, `heatmap-cell-<TICKER>` (attribute `data-pnl-percent`), `heatmap-empty` | treemap |
| `pnl-chart`, `pnl-chart-empty` | P&L chart |
| `chat-panel`, `chat-toggle`, `chat-input`, `chat-send`, `chat-typing`, `chat-message-user`, `chat-message-assistant`, `chat-action` (attribute `data-status="executed|failed"`) | chat |
| `toast` / `error-message` | any displayed API error `detail` |

## 7. Ports & commands

- Backend dev: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
- Frontend dev: `cd frontend && npm run dev` (port 3000; proxy/rewrite `/api` to 8000 in dev only, or point at 8000 via env); `npm run build` → `frontend/out/`
- Docker serves the export from `/app/static`; locally, `STATIC_DIR` can point at `frontend/out`.
- Windows host: shell is PowerShell/Git Bash; Docker Desktop must be running for docker work.
