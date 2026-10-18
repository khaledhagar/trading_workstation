# Market Data Interface: Unified Python API

The contract for how the backend gets stock prices. One abstract interface, `MarketDataSource`, has two implementations:

- **`SimulatorSource`**, used when `MASSIVE_API_KEY` is absent or empty (the default). Its internals are in [`MARKET_SIMULATOR.md`](MARKET_SIMULATOR.md).
- **`MassiveSource`**, used when `MASSIVE_API_KEY` is set. The API research behind it is in [`MASSIVE_API.md`](MASSIVE_API.md).

Both write into one shared **`PriceCache`**. Everything downstream (SSE stream, trade execution, portfolio valuation, watchlist API, LLM context) reads **only the cache** and never knows which source is running. This implements PLAN.md §6.

---

## 1. Design Goals

| Goal | How |
|---|---|
| Source-agnostic downstream code | Sources only *write* the cache; consumers only *read* it |
| Never block the event loop | Everything is `asyncio`; HTTP uses `httpx.AsyncClient`; the simulator is pure CPU work of microseconds per tick |
| A trade right after an add always has a price | `add_ticker()` validates **and** seeds the cache before returning (PLAN.md §6, Tracked Tickers) |
| Works on every Massive plan | `MassiveSource` auto-detects **snapshot** mode (paid) or **end-of-day** mode (free) |
| Testable without a network or a clock | Pure functions for the math and parsing; injectable RNG, HTTP transport and sleep interval |
| Small | A handful of public names (§9): `PriceCache`, `PriceUpdate`, `MarketDataSource`, `create_market_data_source`, `normalize_ticker`, `price_events`, plus two exceptions |

---

## 2. Module Layout

```
backend/app/market/
├── __init__.py        # public re-exports (see §9)
├── models.py          # PriceUpdate dataclass
├── tickers.py         # normalize_ticker(), InvalidTickerError, UnknownTickerError
├── cache.py           # PriceCache
├── base.py            # MarketDataSource ABC
├── factory.py         # create_market_data_source()
├── stream.py          # SSE event generator (reads the cache)
├── simulator/
│   ├── __init__.py
│   ├── seeds.py       # default tickers: seed price, drift, volatility, sector
│   ├── engine.py      # pure GBM engine: no asyncio, no cache
│   └── source.py      # SimulatorSource: runs the engine on a loop, writes the cache
└── massive/
    ├── __init__.py
    ├── client.py      # MassiveClient: thin async httpx wrapper + rate limiter
    ├── parse.py       # pure functions: raw JSON → (price, reference, timestamp)
    └── source.py      # MassiveSource: polling loop, snapshot/EOD modes
```

`backend/` is a uv project (PLAN.md §4). The package name `app` is a proposal; only the shape matters.

Dependencies: `httpx` (needed anyway for FastAPI testing) and `tzdata` (Windows has no IANA time-zone database, and `zoneinfo` needs one for `America/New_York`). The simulator uses only the standard library.

---

## 3. Core Types

### 3.1 `PriceUpdate`: one cache entry

```python
# models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Direction = Literal["up", "down", "flat"]

@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float            # rounded to 2 decimals
    previous_price: float   # price before this update (== price on the first update)
    reference_price: float  # baseline for change % (seed price or previous close)
    timestamp: datetime     # timezone-aware UTC

    @property
    def direction(self) -> Direction:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def change_percent(self) -> float:
        if not self.reference_price:
            return 0.0
        return round((self.price - self.reference_price) / self.reference_price * 100, 2)

    def to_dict(self) -> dict:
        """Exact SSE / GET /api/watchlist field set from PLAN.md §6 and §8."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "direction": self.direction,
            "change_percent": self.change_percent,
        }
```

`direction` compares **rounded** prices, which is what the user sees. A move smaller than a cent is `"flat"`, so no flash fires.

### 3.2 `PriceCache`: the shared state

```python
# cache.py
from datetime import datetime, timezone

class PriceCache:
    """Latest price per ticker. Written by exactly one source, read by everyone.

    All access happens on the asyncio event loop thread, so no locks are needed.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self.version: int = 0          # bumped on every write; cheap change detection

    def update(
        self,
        ticker: str,
        price: float,
        reference_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> PriceUpdate:
        """Record a new price. previous_price comes from the old entry.
        reference_price: if None, keep the old reference; on the first write, use the price itself."""
        old = self._prices.get(ticker)
        price = round(price, 2)
        entry = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            reference_price=(
                reference_price if reference_price is not None
                else old.reference_price if old
                else price
            ),
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        self._prices[ticker] = entry
        self.version += 1
        return entry

    def get(self, ticker: str) -> PriceUpdate | None: ...
    def get_price(self, ticker: str) -> float | None: ...      # convenience for trades
    def snapshot(self) -> dict[str, PriceUpdate]: ...          # shallow copy
    def remove(self, ticker: str) -> None: ...                 # bumps version
    def __contains__(self, ticker: str) -> bool: ...
```

Rules:

- Only the active `MarketDataSource` calls `update()` / `remove()`. Request handlers never write prices.
- The cache never invents prices. A ticker that isn't in it has **no price yet**, and consumers handle that (`null` in `GET /api/watchlist`, omitted from SSE, a 400 on trades).

### 3.3 Ticker rules & errors

```python
# tickers.py
import re

TICKER_RE = re.compile(r"^[A-Z][A-Z.]{0,9}$")

class InvalidTickerError(ValueError):
    """Ticker fails the format rule. API maps it to 400 "Invalid ticker"."""

class UnknownTickerError(LookupError):
    """Well-formed, but the data source has no data for it. API maps it to 400 "Unknown ticker: XYZ"."""
    def __init__(self, ticker: str):
        super().__init__(f"Unknown ticker: {ticker}")
        self.ticker = ticker

def normalize_ticker(raw: str) -> str:
    """Trim + uppercase + validate (PLAN.md §6 Ticker Rules). Raises InvalidTickerError."""
    ticker = raw.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise InvalidTickerError("Invalid ticker")
    return ticker
```

Normalization happens at the API/LLM boundary. Sources receive already-normalized tickers.

---

## 4. The `MarketDataSource` Interface

```python
# base.py
from abc import ABC, abstractmethod
from collections.abc import Iterable

class MarketDataSource(ABC):
    """Produces prices for a set of tracked tickers and writes them into a PriceCache."""

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin tracking `tickers` and launch the background task. Returns quickly:
        it must not wait on slow network work. Called once, in the FastAPI lifespan."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task and release resources (HTTP client). Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking `ticker`. On return the cache HAS a price for it.
        Raises UnknownTickerError if the source can't price it. No-op if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker` and remove it from the cache. No-op if not tracked."""

    @abstractmethod
    def tracked_tickers(self) -> frozenset[str]:
        """The tickers currently being priced."""

    async def sync_tickers(self, desired: Iterable[str]) -> None:
        """Make the tracked set equal `desired` (concrete helper, shared by both sources).
        Removes extras; adds missing ones and logs (not raises) UnknownTickerError,
        because these tickers are already persisted."""
        desired = set(desired)
        current = self.tracked_tickers()
        for t in current - desired:
            await self.remove_ticker(t)
        for t in desired - current:
            try:
                await self.add_ticker(t)
            except UnknownTickerError:
                logger.warning("Tracked ticker %s has no market data", t)
```

### Behaviour contract (both implementations must pass the same tests)

| # | Rule |
|---|---|
| C1 | After `await start(ts)`, every `t in ts` the source can price appears in the cache **eventually**: within one tick (simulator) or one poll (Massive) |
| C2 | After `await add_ticker(t)` returns, `t in cache` is **True** |
| C3 | `add_ticker(t)` for an already-tracked `t` returns immediately with no network call |
| C4 | After `await remove_ticker(t)`, `t not in cache` and the background task never writes `t` again |
| C5 | The background task survives errors: an exception in one tick/poll is logged, the last prices stay in the cache, and the loop continues |
| C6 | `stop()` is idempotent and leaves no running tasks |
| C7 | The cache's `reference_price` for a ticker is stable for the life of the process (simulator) or the trading day (Massive) |
| C8 | Sources never touch the database; the tracked set is pushed in by the app (§7) |

Concurrency: the source's loop and request handlers both run on the single event loop. `add_ticker`/`remove_ticker` mutate the tracked set between `await` points, so no lock is needed. The loop takes a fresh `frozenset` copy of the set at the start of each tick/poll.

---

## 5. `MassiveSource`

### 5.1 Two modes, auto-detected

| Mode | Plans | Endpoint | Price | Reference | Default interval |
|---|---|---|---|---|---|
| `snapshot` | Starter, Developer, Advanced | Full Market Snapshot filtered by `tickers=` (MASSIVE_API.md §2.1). **One call per poll** for all tracked tickers | `lastTrade.p` → `min.c` → `day.c` → `prevDay.c` | `prevDay.c` | **15 s** |
| `eod` | Basic (free) | Daily Market Summary for the **two latest trading days** (§2.3). One call returns the whole market | latest day's `c` | previous day's `c` | refresh every **30 min** |

Detection happens in `start()`'s background task, on the first poll:

1. Call the snapshot endpoint for the tracked tickers.
2. **200** → `snapshot` mode.
3. **403** → `eod` mode (log *"Massive plan has no snapshot access; using end-of-day prices"*).
4. Anything else → log it, wait, retry detection on the next interval. Until a mode is known, the cache stays empty.

`MASSIVE_MODE=snapshot|eod` (optional) skips detection. It's useful for tests, and to save one call on the free tier.

The free tier really can't do better than end-of-day: Basic only has end-of-day data, so PLAN.md §6's "free tier: poll every 15 seconds" isn't achievable. In `eod` mode prices are static during the day and every SSE tick reports `direction: "flat"`. That's correct for the data available. The simulator remains the default and the better demo.

### 5.2 Polling loop

```python
# massive/source.py (shape, not final code)
class MassiveSource(MarketDataSource):
    def __init__(self, cache, api_key, *, poll_interval=15.0, eod_refresh=1800.0,
                 mode=None, transport=None): ...

    async def start(self, tickers):
        self._tickers = set(tickers)
        self._client = MassiveClient(self._api_key, transport=self._transport,
                                     min_interval=None)   # tightened to 12s if eod mode
        self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def _run(self):
        while True:
            try:
                if self._mode is None:
                    await self._detect_mode()        # may itself complete a first poll
                elif self._mode == "snapshot":
                    await self._poll_snapshot(frozenset(self._tickers))
                else:
                    await self._refresh_eod_if_due()
            except asyncio.CancelledError:
                raise
            except Exception:                        # C5
                logger.exception("Massive poll failed; keeping last prices")
            await asyncio.sleep(self._interval())

    async def _poll_snapshot(self, tickers):
        if not tickers:
            return
        snaps = await self._client.snapshots(tickers)          # {ticker: raw}
        for t, snap in snaps.items():
            if t not in self._tickers:                         # removed mid-poll (C4)
                continue
            parsed = parse_snapshot(snap)                      # (price, ref, ts) | None
            if parsed:
                self.cache.update(t, parsed.price, parsed.reference, parsed.timestamp)
```

Each poll, `previous_price` comes from the cache's previous entry, so `direction` reflects poll-over-poll movement.

### 5.3 `MassiveClient`: thin HTTP layer

```python
# massive/client.py
class MassiveError(Exception): ...
class PlanNotEntitledError(MassiveError): ...   # HTTP 403
class RateLimitedError(MassiveError): ...        # HTTP 429

class MassiveClient:
    BASE_URL = "https://api.massive.com"

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 10.0, min_interval: float | None = None): ...

    async def snapshots(self, tickers: Iterable[str]) -> dict[str, dict]:
        """GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=A,B,C"""

    async def grouped_daily(self, day: date) -> dict[str, float]:
        """GET /v2/aggs/grouped/locale/us/market/stocks/{day} → {ticker: close}. {} if no data."""

    async def aclose(self) -> None: ...
```

- Auth: `Authorization: Bearer <key>`. The key is never logged or put in URLs.
- **No automatic retries.** The next poll is the retry, so a 429 never multiplies.
- Status mapping: 403 → `PlanNotEntitledError`, 429 → `RateLimitedError`, other non-2xx → `MassiveError`. Network errors and timeouts become `MassiveError`.
- `min_interval`: when set (12 s in `eod` mode), each call first awaits until at least `min_interval` has passed since the previous call. This keeps the free tier under 5 calls/minute even when an add, a refresh and the startup lookups coincide.
- `transport` is injectable, so tests use `httpx.MockTransport` with canned JSON from MASSIVE_API.md.

### 5.4 `eod` mode details

- `_refresh_eod()` uses the "latest two trading days" walk (MASSIVE_API.md §4.2). Dates come from `datetime.now(ZoneInfo("America/New_York"))`, weekends are skipped without a call, and empty days (holidays, not yet published) are skipped. At most 5 calls.
- It keeps two **whole-market** maps in memory, `self._latest: dict[str, float]` and `self._previous: dict[str, float]` (~10k entries each, about 1 MB), then writes `cache.update(t, latest[t], previous.get(t))` for every tracked ticker.
- A refresh every 30 minutes picks up the new trading day once Massive publishes it. Between refreshes the loop does nothing, so it uses 0 calls.
- The SSE stream still emits every 500 ms from the cache (§6), so the connection dot stays green.

### 5.5 `add_ticker` per mode (C2)

| Mode | What `add_ticker("XYZ")` does | API calls |
|---|---|---|
| `snapshot` | `snapshots(["XYZ"])`. Empty result or unparseable → `UnknownTickerError`. Otherwise seed the cache from that response, then add XYZ to the tracked set | 1 |
| `eod` | Look XYZ up in `self._latest`. Missing → `UnknownTickerError`. Otherwise `cache.update(...)` from the maps, then add to the tracked set | **0** |
| not yet detected (first seconds after boot) | Wait for the first detection/refresh to finish (an `asyncio.Event`, 15 s timeout), then follow the mode's row. On timeout → `MassiveError` (the API returns 503 *"Market data unavailable, try again"*) | — |

Startup: `start()` returns immediately, and the first poll runs in the background. Until it completes, `GET /api/watchlist` shows `null` prices and trades get 400 *"No price available for XYZ yet"* (PLAN.md §6 fallback). Both resolve within seconds.

### 5.6 Parsing (pure, unit-tested)

```python
# massive/parse.py
@dataclass(frozen=True)
class ParsedPrice:
    price: float
    reference: float | None
    timestamp: datetime

def parse_snapshot(snap: dict) -> ParsedPrice | None:
    """Fallback chain lastTrade.p → min.c → day.c → prevDay.c; zeros count as missing.
    timestamp from `updated` (ns) → UTC datetime; falls back to now().
    Returns None if no usable price (e.g. during the 3:30–4:00 AM ET reset)."""
```

---

## 6. SSE Stream (reads the cache)

```python
# stream.py
async def price_events(cache: PriceCache, request: Request, interval: float = 0.5):
    while not await request.is_disconnected():
        payload = {t: u.to_dict() for t, u in cache.snapshot().items()}
        yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        await asyncio.sleep(interval)

# route (api layer):
# @router.get("/api/stream/prices")
# async def stream_prices(request: Request):
#     return StreamingResponse(price_events(app.state.price_cache, request),
#                              media_type="text/event-stream",
#                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- One unnamed event every 500 ms with **all** tracked tickers, keyed by ticker, exactly the PLAN.md §6 format. Tickers not in the cache are naturally omitted.
- It emits **every tick even if nothing changed**. That keeps the frontend's 5-second staleness rule green while Massive polls every 15 s (or refreshes every 30 min in `eod` mode).
- **Frontend note:** with Massive, many consecutive events carry the same `timestamp` for a ticker. The sparkline/chart buffers should append a point **only when `timestamp` changes** for that ticker; otherwise a 15-second poll becomes 30 identical points. With the simulator every tick has a new timestamp, so this rule is harmless.
- No server-side per-client state, so many tabs are fine.

---

## 7. Integration With the App

### 7.1 Factory

```python
# factory.py
def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        logger.info("Market data: Massive API")
        return MassiveSource(
            cache,
            api_key,
            poll_interval=float(os.getenv("MASSIVE_POLL_INTERVAL", "15")),
            mode=os.getenv("MASSIVE_MODE") or None,      # "snapshot" | "eod" | None = auto
        )
    logger.info("Market data: simulator")
    return SimulatorSource(cache)
```

### 7.2 Lifespan (PLAN.md §7: DB first, then market data)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(PROJECT_ROOT / ".env")                  # PLAN.md §5
    init_db()                                           # schema + seed
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(db.tracked_tickers())            # watchlist ∪ open positions
    app.state.price_cache, app.state.market = cache, source
    snapshot_task = asyncio.create_task(portfolio_snapshot_loop(app))
    try:
        yield
    finally:
        snapshot_task.cancel()
        await source.stop()
```

### 7.3 Keeping the tracked set = watchlist ∪ positions

The DB is the source of truth, and the market source mirrors it. After any change that can alter the set, the service layer calls:

```python
await app.state.market.sync_tickers(db.tracked_tickers())
```

| Event | Effect on tracked set |
|---|---|
| `POST /api/watchlist` (add) | Call `await market.add_ticker(t)` **before** inserting the row, so validation (`UnknownTickerError` → 400) and seeding happen first, then insert |
| `DELETE /api/watchlist/{t}` | Delete the row, then `sync_tickers` (no change if `t` is still held) |
| Buy of an unwatched ticker | Same as an add (PLAN.md §8 auto-adds it to the watchlist), then trade |
| Sell to zero | Delete the position, then `sync_tickers` (drops `t` only if not watched) |
| Chat actions | Same calls; `watchlist_changes` before `trades` |

Trade execution reads its fill price with `cache.get_price(t)` **inside** the `BEGIN IMMEDIATE` transaction. `None` → 400 `"No price available for XYZ yet"`.

### 7.4 Who uses what

| Consumer | Reads |
|---|---|
| `GET /api/stream/prices` | `cache.snapshot()` every 500 ms |
| `GET /api/watchlist` | `cache.get(t)` per watchlist row (`null` fields if missing) |
| Trades (manual + LLM) | `cache.get_price(t)` |
| `GET /api/portfolio`, snapshot task | `cache.get_price(t)` per position (fall back to `avg_cost` if a held ticker somehow has no price, so valuations never crash) |
| LLM context | `cache.snapshot()` for watchlist prices and change % |

---

## 8. Configuration Summary

| Env var | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | Empty → simulator. Set → `MassiveSource` |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between snapshot polls (paid plans; 2–15 is sensible) |
| `MASSIVE_MODE` | auto | Force `snapshot` or `eod` |

`MASSIVE_POLL_INTERVAL` and `MASSIVE_MODE` are **new optional variables** proposed here. They should be added to PLAN.md §5 and `.env.example` if accepted. Simulator tuning stays in code (`simulator/seeds.py`), not env vars.

---

## 9. Public API (`app/market/__init__.py`)

```python
from .cache import PriceCache
from .models import PriceUpdate
from .base import MarketDataSource
from .factory import create_market_data_source
from .tickers import normalize_ticker, InvalidTickerError, UnknownTickerError
from .stream import price_events
```

Nothing outside `app/market/` imports from `simulator/` or `massive/` directly.

---

## 10. Testing

| Test | What it proves |
|---|---|
| `PriceUpdate` direction / change % / `to_dict` | Rounding, flat on sub-cent moves, ISO `Z` timestamp |
| `PriceCache.update` | `previous_price` chaining, reference kept or replaced, `version` bump |
| `normalize_ticker` | `" aapl "`→`AAPL`, `BRK.B` ok, `1ABC`/`TOOLONGTICKER`/`""` rejected |
| **Contract suite** (parametrized over both sources) | C1–C6 from §4: add seeds the cache, remove stops writes, errors don't kill the loop, stop is idempotent |
| `parse_snapshot` | Each fallback step, zeros skipped, ns→UTC, `None` when nothing is usable |
| `MassiveSource` with `httpx.MockTransport` | 200 → snapshot mode, 403 → eod mode, 429 → keeps prices, unknown ticker → `UnknownTickerError`, eod add costs 0 calls, the free-tier limiter spaces calls ≥ 12 s (fake clock) |
| `price_events` | Event format matches PLAN.md §6, missing tickers omitted, emits while unchanged |

Run the simulator in tests with a fixed RNG seed and a tiny interval (`SimulatorSource(cache, interval=0.01, rng=random.Random(42))`).
