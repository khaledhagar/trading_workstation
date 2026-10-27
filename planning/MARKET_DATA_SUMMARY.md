# Market Data: Summary & Key Reference

One-page reference for everything market-data related, condensed from the planning documents now kept in [`archive/`](archive/). [`PLAN.md`](PLAN.md) stays the project spec. Where the archived documents disagree with each other, `MARKET_DATA_DESIGN.md` won, and this summary follows it.

| Archived document | What it was |
|---|---|
| [`archive/MARKET_DATA_DESIGN.md`](archive/MARKET_DATA_DESIGN.md) | Implementation design with full code for every module (authoritative) |
| [`archive/MARKET_INTERFACE.md`](archive/MARKET_INTERFACE.md) | The `MarketDataSource` contract (C1–C8) and module layout |
| [`archive/MARKET_SIMULATOR.md`](archive/MARKET_SIMULATOR.md) | GBM + two-factor correlation + events model |
| [`archive/MASSIVE_API.md`](archive/MASSIVE_API.md) | Massive (Polygon.io) REST research: plans, endpoints, response shapes, gotchas |
| [`archive/REVIEW.md`](archive/REVIEW.md) | Code review of the market data backend and how each finding was resolved |
| [`archive/PLAN_REVIEW.md`](archive/PLAN_REVIEW.md) | Spec review log (questions 1–34), all resolved into PLAN.md |

**Status (2026-10-27):** the market data package `backend/app/market/` is complete, reviewed and tested (249 tests pass, 99% coverage). A live terminal demo exists (`cd backend && uv run python demo.py`). Not built yet: the FastAPI app around it (§11).

---

## 1. Architecture in Three Rules

```
SimulatorSource (tick 500 ms)  ─┐                ┌─> GET /api/stream/prices (SSE)
            or                  ├─> PriceCache ──┼─> GET /api/watchlist
MassiveSource (poll 15 s /      ┘  (in memory)   ├─> trades (fill price)
  EOD refresh 30 min)                            ├─> GET /api/portfolio + snapshot task
                                                 └─> LLM context
```

1. **Sources only write the cache; everything else only reads it.** No consumer knows which source runs.
2. **The database owns the tracked set** = watchlist ∪ open positions. The app pushes it into the source; sources never touch the DB.
3. **Everything runs on one asyncio event loop.** No threads, no locks. The only network I/O is `httpx.AsyncClient`.

Source choice: `MASSIVE_API_KEY` empty → simulator (default, best demo); set → Massive.

---

## 2. Design Decisions (D1–D12)

| # | Decision | Why |
|---|---|---|
| D1 | Timestamps have **milliseconds**: `2026-01-01T12:00:00.500Z` | Simulator ticks every 500 ms; whole seconds would collide and the frontend's "new point only on new timestamp" rule would drop half |
| D2 | Errors in `errors.py`, plus `MarketDataUnavailableError` → **HTTP 503**. `MassiveError` subclasses it | Provider down / rate-limited / loading is neither a bad ticker (400) nor a bug (500) |
| D3 | **Free Massive plan = end-of-day mode**, refreshed every 30 min, auto-detected from a 403 | Snapshots aren't on the free plan |
| D4 | In EOD mode a **403 for a date = "no data for that day"** | Free tier refuses today's grouped data before it's published; the day walk moves on |
| D5 | Simulator **doesn't burst after a stall** | After laptop sleep / debugger pause it resets its schedule instead of firing catch-up ticks |
| D6 | Detection **probes `AAPL` when nothing is tracked** | An empty `tickers=` returns the whole market (10k+ rows). Never send it empty |
| D7 | `PriceCache.version` dropped | Nothing reads it |
| D8 | `add_ticker` waits **at most 20 s** for Massive's first load, then 503 | First EOD load can take ~25–40 s on the free tier |
| D9 | **Cache never holds a price < $0.01 after rounding.** Parsers skip sub-cent values (ticker → unknown); simulator floors at $0.01 | Review finding: `0.004` was stored as `0.00` → free trades |
| D10 | Snapshot with **all price fields zero → 503**, not "Unknown ticker" | That's Massive's 3:30–4:00 AM ET reset; the ticker is real |
| D11 | Free-tier call spacing **12.5 s** (not 12) | Margin for network jitter within 5 calls/min |
| D12 | `MassiveSource.client` raises `MarketDataUnavailableError` before `start()`/after `stop()`; a second `SimulatorSource.start()` doesn't re-seed tracked tickers | Contract errors map to 503 not 500; C7 always holds |

---

## 3. Module Layout & Public API

```
backend/app/market/
├── __init__.py      # public API (below)
├── errors.py        # InvalidTickerError, UnknownTickerError, MarketDataUnavailableError
├── tickers.py       # normalize_ticker()
├── models.py        # PriceUpdate, format_timestamp()
├── cache.py         # PriceCache, MIN_PRICE, is_priceable()
├── base.py          # MarketDataSource ABC (+ sync_tickers)
├── factory.py       # create_market_data_source(cache, env=os.environ)
├── stream.py        # price_events() SSE generator
├── simulator/       # seeds.py, engine.py (pure math), source.py
└── massive/         # parse.py (pure), client.py (httpx + rate limiter), source.py
backend/demo.py      # live terminal demo
backend/tests/       # market/ (fakes.py + 10 test files), test_demo.py
```

Public names (code outside `app/market/` imports only these): `MarketDataSource`, `PriceCache`, `PriceUpdate`, `InvalidTickerError`, `UnknownTickerError`, `MarketDataUnavailableError`, `create_market_data_source`, `normalize_ticker`, `price_events`.

Dependencies: `fastapi`, `uvicorn[standard]`, `httpx`, `python-dotenv`, `tzdata` (zoneinfo on Windows/slim images). Dev: `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`), `pytest-cov`. Simulator uses only the standard library (no numpy). Python ≥ 3.12, managed with uv.

---

## 4. Core Types

### Tickers & errors

- `normalize_ticker(raw)`: must be a `str`; trim + uppercase; must fully match `[A-Z][A-Z.]{0,9}` (e.g. `AAPL`, `BRK.B`). Done **once at the boundary** (API route / LLM action).

| Error | Meaning | HTTP |
|---|---|---|
| `InvalidTickerError` (ValueError) | Fails the format rule | 400 `"Invalid ticker"` |
| `UnknownTickerError` (LookupError) | Well-formed, source has no data | 400 `"Unknown ticker: XYZ"` |
| `MarketDataUnavailableError` | Provider down / rate-limited / still loading / not running | 503 `"Market data unavailable, try again shortly"` (fixed text; details only in logs) |

All three subclass `MarketDataError`. Massive client errors (`MassiveError` and subclasses) subclass `MarketDataUnavailableError`.

### `PriceUpdate` (frozen dataclass, one cache entry)

Fields: `ticker`, `price` (rounded to 2 dp), `previous_price` (= price on first write), `reference_price` (baseline for change %), `timestamp` (UTC).

- `direction`: `"up"` / `"down"` / `"flat"`, comparing **rounded** prices, so sub-cent moves are flat (no flash).
- `change_percent` = `round((price − reference) / reference × 100, 2)`; 0.0 if reference ≤ 0.
- `to_dict()` → exactly `ticker, price, previous_price, timestamp, direction, change_percent` (the SSE entry and `GET /api/watchlist` row). `reference_price` is internal.
- `format_timestamp()` → ISO 8601 UTC, milliseconds, `Z`.

### `PriceCache`

- `update(ticker, price, reference_price=None, timestamp=None)`: raises `ValueError` unless `is_priceable(price)` (finite number, not bool, ≥ `MIN_PRICE` = 0.01 after rounding). An invalid reference is ignored. `reference_price=None` keeps the old reference (first write: the price itself). `previous_price` chains from the old entry.
- `get`, `get_price`, `snapshot()` (shallow copy), `remove`, `in`, `len`.
- Only the active source writes. The cache never invents prices: missing = "no price yet".

Example: seed `190.0` (ref 190.0), tick `190.123` → price 190.12, previous 190.0, direction up, change 0.06%.

---

## 5. The `MarketDataSource` Interface

Abstract methods: `async start(tickers)` (returns quickly; called once in the lifespan), `async stop()` (idempotent), `async add_ticker(t)` (on return the cache **has** a price; raises Unknown/Unavailable; no-op if tracked), `async remove_ticker(t)` (removes from cache; no-op if not tracked), `tracked_tickers() -> frozenset`.

Concrete `sync_tickers(desired)`: removes extras, adds missing ones, and **logs** (doesn't raise) Unknown/Unavailable errors, because those tickers are already persisted.

### Behaviour contract (both sources pass the same tests)

| # | Rule |
|---|---|
| C1 | After `start(ts)`, every priceable ticker appears in the cache (simulator: immediately; Massive: within one poll) |
| C2 | After `add_ticker(t)` returns, `t in cache` |
| C3 | `add_ticker` on a tracked ticker returns immediately, no network call |
| C4 | After `remove_ticker(t)`, `t` is gone and the loop never writes it again |
| C5 | The background loop survives errors: logged, last prices kept, loop continues |
| C6 | `stop()` is idempotent, leaves no running task |
| C7 | `reference_price` is stable for the process life (simulator) or the trading day (Massive) |
| C8 | Sources never touch the database |

No locks needed: a source never awaits between reading its tracked set and writing the cache. Where an await is unavoidable (HTTP), it re-checks membership afterwards (`_apply_snapshots`).

---

## 6. The Simulator

### Model

```
S(t+Δt) = S(t) · exp((μ − σ²/2)·Δt + σ·√Δt·Z)       exact GBM step, never negative
Z_i     = w_m·M + w_s·S_sector(i) + w_e·ε_i          w_m² + w_s² + w_e² = 1
Δt      = 0.5 s / (252 × 6.5 × 3600 s) ≈ 8.48e-8     real-market speed (× time_scale)
event:    S ← S · (1 ± U(0.02, 0.05)), p = 0.5/600 per ticker per tick
```

- **Correlation** (two-factor, O(1) add/remove, no matrix): defaults `w_m = w_s = √0.3`, `w_e = √0.4` → **0.6** same sector, **0.3** cross sector, **0** for unknown tickers (sector `None` uses pure own noise).
- **Events:** ~1 per ticker per 10 min ≈ **1 per minute across 10 tickers**; logged at DEBUG (`event: TSLA -3.4%`).
- **Magnitudes (1σ):** AAPL ≈ $0.014/tick, 0.6%/hour; TSLA ≈ $0.044/tick, 1.5%/hour; V ≈ $0.014/tick, 0.4%/hour. ~73% of ticks change the cent-rounded price, so the watchlist flickers constantly.
- **`time_scale`** (constructor arg, default 1; not an env var): 60 makes each second a trading minute (demo `--fast`).
- Engine keeps **full-precision** prices (rounding in the cache), else low-vol tickers stall. Floors at $0.01 (D9). Deterministic given a seeded `random.Random`.
- Engine validates `tick_seconds > 0`, `time_scale > 0`, `w_m² + w_s² ≤ 1`. `event_mean_seconds=inf` disables events.

### Seeds (`simulator/seeds.py`)

| Ticker | Seed | μ | σ | Sector |
|---|---|---|---|---|
| AAPL | 190 | 0.08 | 0.25 | tech |
| GOOGL | 175 | 0.08 | 0.28 | tech |
| MSFT | 420 | 0.08 | 0.24 | tech |
| META | 500 | 0.10 | 0.35 | tech |
| NVDA | 130 | 0.15 | 0.50 | tech |
| AMD | 160 | 0.12 | 0.50 | tech |
| AMZN | 185 | 0.10 | 0.30 | consumer |
| TSLA | 250 | 0.10 | 0.60 | consumer |
| NFLX | 650 | 0.10 | 0.40 | consumer |
| DIS | 100 | 0.06 | 0.28 | consumer |
| JPM | 200 | 0.06 | 0.20 | finance |
| V | 275 | 0.06 | 0.18 | finance |
| BAC | 40 | 0.06 | 0.25 | finance |
| PYPL | 70 | 0.05 | 0.40 | finance |

First ten = PLAN.md §7 default watchlist. **Unknown tickers:** random seed in **$50–$300** (rounded to cents), μ 0.05, σ 0.30, sector `None` (uncorrelated). The simulator accepts any well-formed ticker and never raises `UnknownTickerError`.

### Reference price & lifecycle

- On add, the seed is written as both `price` and `reference_price` → change % starts at 0.00%. The reference never changes while the process runs. A restart re-seeds everything (no persistence). Remove + re-add re-seeds.
- `SimulatorSource(cache, interval=0.5, rng=None, time_scale=1.0, engine=None)`. `start()` seeds untracked tickers synchronously, then launches a fixed-cadence loop (sleep until `next_tick`, exactly 2 ticks/s, no burst after a stall). No awaits inside a tick. A tick for 10–50 tickers takes well under 1 ms.
- **Deliberate non-features:** no market hours (trades 24/7), no mean reversion or volatility clustering, no price persistence, no order-book impact from user trades.

---

## 7. The Massive Source (optional, real data)

### Plans (researched 2026-10-18)

| Plan | $/month | Rate limit | Data | Snapshots |
|---|---|---|---|---|
| Basic (free) | 0 | **5 calls/min** | End-of-day, 2 y history | ❌ (403) |
| Starter | 29 | Unlimited | 15-min delayed | ✅ (no `lastTrade`) |
| Developer | 79 | Unlimited | 15-min delayed | ✅ |
| Advanced | 199 | Unlimited | Real-time | ✅ |

Base URL `https://api.massive.com` (old `api.polygon.io` still works). Auth: `Authorization: Bearer <key>` (the key is never put in URLs or logs). Tickers are case-sensitive uppercase; dotted tickers (`BRK.B`) as-is. Timestamps: bars in **ms**, trades/quotes/snapshot `updated` in **ns**.

### Endpoints used

| Endpoint | Plans | Use |
|---|---|---|
| `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=A,B` | Paid | Snapshot mode: one call for all tickers. Unknown tickers are simply **absent**. Empty filter = whole market (never send empty, D6) |
| `GET /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD}?adjusted=true` | All | EOD mode: every US stock's OHLC for a day (~10k rows, ~1 MB gzip). `T` = ticker, `c` = close. Weekend/holiday/unpublished → empty results |

Not used, documented in the archive: single-ticker snapshot, previous-day bar, open/close (pre-market/after-hours), custom bars (for future chart history), v3 unified snapshot (≤ 250, paginated), last trade (Developer+), market status, ticker overview. The official `massive` Python client is **synchronous** with hidden retries (3, which multiply 429s on the free tier), so the backend uses `httpx.AsyncClient` directly.

### Two modes

| | `snapshot` | `eod` |
|---|---|---|
| Plans | Starter+ | Basic (free) |
| Calls | 1 per poll, any number of tickers | ~2–3 per refresh, whole market |
| Interval | `MASSIVE_POLL_INTERVAL` (default 15 s, min 2) | every 30 min |
| Price | first value ≥ $0.01 of `lastTrade.p` → `min.c` → `day.c` → `prevDay.c` | latest trading day's close |
| Reference | `prevDay.c` (previous close) | close of the trading day before |
| Timestamp | snapshot `updated` (ns → UTC) | 16:00 New York time on the latest day |
| Add a ticker | 1 snapshot call (validates + seeds) | **0 calls** (lookup in the in-memory map) |
| Rate limiting | none | calls spaced ≥ 12.5 s |

**Detection** (unless `MASSIVE_MODE` forces it): first loop iteration calls the snapshot for the tracked tickers (or `AAPL`). 200 → snapshot mode; 403 → EOD mode (log *"Massive plan has no snapshot access; using end-of-day prices"*) and load two trading days; other error → retry after backoff. `MASSIVE_MODE=eod` saves one call and 12 s on a free key.

**EOD day walk:** from today (New York time), skip weekends without a call; holidays, unpublished days and 403s (D4) cost one call each; stop after two days with data, at most 5 calls. Keeps two whole-market maps (`_latest`, `_previous`) in memory. In EOD mode `direction` is `"flat"`, except for one refresh after a new trading day loads.

**`add_ticker` per mode:**

| Case | Result |
|---|---|
| Already tracked | Return immediately (C3) |
| Mode not detected / EOD not loaded yet | Wait for readiness, max 20 s (D8), then 503 |
| Snapshot: ticker absent from response | `UnknownTickerError` (400) |
| Snapshot: present, every price field zero | `MarketDataUnavailableError` (503, D10) |
| Snapshot: present, only sub-cent prices | `UnknownTickerError` (D9) |
| EOD: not in the loaded map | `UnknownTickerError` |
| Otherwise | Seed the cache, then add to the tracked set |

**Client status mapping** (branch on status code, never message text; **no automatic retries**: the next poll is the retry):

| HTTP | Exception | Loop reaction |
|---|---|---|
| 401 | `MassiveAuthError` | Log, keep prices, retry next poll |
| 403 | `PlanNotEntitledError` | Detection → EOD mode; for a date → empty day |
| 429 | `RateLimitedError` | Back off 60 s |
| other ≥ 400, network error, timeout (10 s), bad JSON | `MassiveError` | Log, keep prices; retry after poll interval (snapshot) or 60 s (EOD) |

`MassiveSource` params: `mode`, `poll_interval=15`, `eod_refresh=1800`, `error_backoff=60`, `free_tier_spacing=12.5`, `ready_timeout=20`, `eod_max_calls=5`, `base_url`, `transport` (inject `httpx.MockTransport` in tests), `today` (clock injection).

### API-call budget

| Situation | Calls |
|---|---|
| Paid, steady state | 1 every 15 s, regardless of ticker count |
| Paid, add a ticker | +1 |
| Free, startup | 3 (probe 403 + 2 grouped days), ~25 s with spacing |
| Free, Monday before publish | 4 |
| Free, every 30 min | 2–3 |
| Free, add a ticker | 0 |

**Gotchas:** 15-min delay on Starter/Developer is fine for a demo; outside market hours prices just stop moving (SSE stays healthy); snapshots reset 3:30–4:00 AM ET (fields zero → last price kept, adds get 503); WebSockets exist on paid plans but are out of scope.

---

## 8. Configuration

| Env var | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | Empty → simulator; set → Massive |
| `MASSIVE_MODE` | auto | `snapshot` / `eod` (case-insensitive) skips detection; invalid → warning + auto |
| `MASSIVE_POLL_INTERVAL` | 15 | Snapshot poll seconds; non-numeric → 15 with warning; below 2 → raised to 2 |

Ignored without a key. Simulator tuning stays in code. The factory takes `env` as a parameter (testable with a dict).

Startup logs: `Market data source: simulator`, or `Market data source: Massive API (mode=auto)` followed by `Massive snapshot mode: polling every 15s` or the EOD warning and `Massive end-of-day prices loaded for 2026-10-16`.

---

## 9. SSE Stream

`price_events(cache, request, interval=0.5)` yields `retry: 2000` first (browser reconnect delay), then **one unnamed event every 500 ms, even if nothing changed** (keeps the frontend's 5 s staleness dot green while Massive changes only every 15 s or once a day), until `request.is_disconnected()`.

```text
retry: 2000

data: {"AAPL":{"ticker":"AAPL","price":190.12,"previous_price":190.05,"timestamp":"2026-10-18T19:00:01.500Z","direction":"up","change_percent":0.06},"TSLA":{...}}
```

- Keyed by ticker, compact JSON, all tracked tickers; tickers without a price are omitted; empty cache → `data: {}`.
- Route: `StreamingResponse(..., media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`. **Don't add `GZipMiddleware`** (it buffers and breaks streaming). No per-client state, so many tabs are fine. Test with `curl -N http://localhost:8000/api/stream/prices`.
- **Frontend rules:** flash on a change of `price` versus the last seen value (not on `direction`, which Massive re-sends for 15 s); append a chart point only when `timestamp` changes; for Lightweight Charts use `Date.parse(ts)/1000` and drop non-increasing times.
- The stream sleeps a flat 0.5 s, so it drifts slightly against the simulator's fixed cadence (an occasional tick skipped or repeated). Cosmetic, left as is.

---

## 10. Integration With the App (designed, not built yet)

**Lifespan (`app/main.py`):** `load_dotenv(<project root>/.env, override=False)` → `db.init_db()` → `PriceCache()` → `create_market_data_source(cache)` → `await market.start(db.tracked_tickers(conn))` → store `app.state.price_cache` / `app.state.market` → start the portfolio snapshot task. Shutdown: cancel the snapshot task, `await market.stop()`. Register error handlers, then `/api` routers, then the static mount. With Massive the cache is empty at the startup snapshot, so valuation falls back to `avg_cost`.

**Tracked set:**

```sql
SELECT ticker FROM watchlist WHERE user_id = ? UNION SELECT ticker FROM positions WHERE user_id = ?
```

`resync_market(app)` = read that set, then `market.sync_tickers(desired)`.

| Event | Market call |
|---|---|
| Startup | `start(tracked_tickers)` |
| `POST /api/watchlist` | `add_ticker(t)` **before** the insert (validate + seed first, so an unknown ticker is never persisted and the response already has the price). Insert is `ON CONFLICT DO NOTHING` (idempotent) |
| `DELETE /api/watchlist/{t}` | Delete the row (404 if absent), then `resync_market` (stays tracked if still held) |
| Buy of an unwatched ticker | Same as an add, then the trade |
| Sell to zero | `resync_market` after the commit (drops `t` if not watched) |
| Chat actions | Same calls; `watchlist_changes` before `trades`; each exception caught per action → `{"status": "failed", "error": str(exc)}` |

**Trades** read the fill price with `cache.get_price(t)` **inside** `BEGIN IMMEDIATE`; `None` → 400 `"No price available for XYZ yet"`.

| Consumer | Reads | When there's no price |
|---|---|---|
| SSE | `cache.snapshot()` every 500 ms | Ticker omitted |
| `GET /api/watchlist` | `cache.get(t)` per row (ordered by `added_at`) | `null` fields |
| Trades | `cache.get_price(t)` | 400 |
| `GET /api/portfolio`, snapshot task | `cache.get_price(t)` | Value at `avg_cost` |
| LLM context | `cache.snapshot()` | "no price yet" |

Example: watchlist AAPL, TSLA, holding 5 TSLA. Deleting TSLA from the watchlist keeps it in SSE (portfolio stays valued); selling 5 TSLA then removes it from the cache and SSE.

---

## 11. Testing & Quality

- Run: `cd backend && uv run pytest` (add `--cov=app` for coverage). No network: Massive is faked with `httpx.MockTransport` (`tests/market/fakes.py`: `FakeMassive`, `make_snapshot`, `wait_until`). Engine tests use a seeded RNG and call `step()` directly; source tests use `interval=0.01`.
- Coverage of PLAN.md §12: GBM math, positivity, σ, correlation (0.6 / 0.3 / 0 ± 0.05), event size and rate, determinism, `time_scale` (`test_engine.py`); parsing (`test_massive_parse.py`); interface conformance for both sources, C1–C6 (`test_contract.py` plus source-specific tests); unknown ticker → 400; SSE format (`test_stream.py`); env-driven source choice (`test_factory.py`); client status mapping, key only in the header, sorted ticker list, no call for an empty list, spacing (`test_massive_client.py`).
- **Results:** 249 passed (241 market + 8 demo), 99% coverage. The only uncovered lines are two defensive ones in `massive/source.py`. No flakes over repeated runs.

### Code review outcome (2026-10-27)

The review approved the implementation, which closely followed the design. All findings were fixed in commit `485f8ae`:

| Finding | Severity | Resolution |
|---|---|---|
| Price < $0.005 stored as `0.00` → free trades | Medium | D9: check after rounding; parsers skip sub-cent; engine floor |
| Real ticker "Unknown" during the 3:30–4:00 AM reset | Low | D10: all-zero snapshot → 503 |
| Second `SimulatorSource.start()` reset references | Low | D12: seed only untracked tickers |
| `MassiveSource.add_ticker` before `start()` → `RuntimeError` (500) | Low | D12: `MarketDataUnavailableError` (503) |
| EOD `direction` up/down for one refresh after a new day | Low | Docs updated (behaviour kept) |
| Free-tier spacing had no margin | Note | D11: 12.5 s |
| SSE cadence drift | Note | No change (cosmetic) |
| Poll-interval clamp wording | Note | PLAN.md §5 reworded |
| `pytest-cov` missing | Note | Added to dev dependencies |

---

## 12. Spec Review Outcomes (from `PLAN_REVIEW.md`)

All 34 questions are resolved and already reflected in PLAN.md. The decisions that shaped market data and its consumers:

- **Contracts:** SSE = one unnamed event per tick, JSON keyed by ticker; FastAPI `{"detail": ...}` errors; ISO 8601 UTC with `Z`; `GET /api/chat/history` added.
- **Market data:** change % baseline = seed (simulator) / previous close (Massive), sent by the backend; tracked set = watchlist ∪ positions; unknown tickers get a random seed in the simulator and are rejected by Massive; trades with no price → 400; one multi-ticker call per poll; no server-side price history (charts fill from SSE).
- **Trading:** fractional shares to 4 dp, cash to cents; full exit deletes the position row; sells keep `avg_cost`; buying an unwatched ticker auto-adds it; one `BEGIN IMMEDIATE` transaction per trade, WAL mode; snapshots always recorded, history returns the last 1,000.
- **LLM:** per-action outcomes, no second call; last 20 messages with action summaries; all schema fields required, `Literal` enums; failure → 200 with an apology; deterministic mock rules; use `acompletion`.
- **DB / Docker / frontend:** init once in the lifespan; `DB_PATH`; named volume `trading-workstation-data`; `.env` via `--env-file` or `load_dotenv`; missing OpenRouter key → chat says it isn't configured; API routers before the static mount; connection-status rules, frontend-computed total value, chart libraries, empty states.
- **Simplifications:** adopted composite keys, frontend-only history, limited frontend unit tests, no root docker-compose. Rejected Playwright-from-host as the only runner, and a longer snapshot interval.

---

## 13. Next Steps

Build the app around the package (archived design §9): `app/main.py` lifespan, `db.py` (`init_db`, `connect`, `tracked_tickers`, `resync_market`), the `/api/stream/prices` route, the market error handlers, and the watchlist/trade wiring. Then the portfolio, chat, health routes and the frontend per PLAN.md.
