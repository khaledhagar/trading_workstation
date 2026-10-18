# Market Data Backend: Detailed Design

The implementation guide for everything market-data related in the backend: the unified API, the simulator, the Massive client, the shared price cache, the SSE stream, and how they plug into the FastAPI app.

It builds on three research/spec documents and turns them into complete, runnable code:

| Document | What it contributes |
|---|---|
| [`PLAN.md`](PLAN.md) §6, §7, §8 | Requirements: tracked tickers, ticker rules, SSE format, trade rules, error codes |
| [`MARKET_INTERFACE.md`](MARKET_INTERFACE.md) | The `MarketDataSource` contract (C1–C8) and module layout |
| [`MARKET_SIMULATOR.md`](MARKET_SIMULATOR.md) | The GBM + two-factor correlation + events model |
| [`MASSIVE_API.md`](MASSIVE_API.md) | Massive endpoints, plan tiers, response shapes, gotchas |

Where this document differs from those, it says so in §0. **For implementation, this document wins.**

---

## 0. Decisions Made in This Design

Most of the design is taken unchanged from the documents above. These are the points this document adds or changes:

| # | Decision | Why |
|---|---|---|
| D1 | **Timestamps carry milliseconds**: `"2026-01-01T12:00:00.500Z"` | The simulator ticks every 500 ms. With whole seconds, two ticks share a timestamp, and the frontend rule "append a chart point only when the timestamp changes" (§8.3) would drop half the points. Still ISO 8601 UTC with `Z`, as PLAN.md §8 requires |
| D2 | **Errors live in `errors.py`**, with a third type, `MarketDataUnavailableError` → **HTTP 503** | Massive can be down, rate-limited or still loading at startup. That is neither a bad ticker (400) nor a server bug (500). `MassiveError` subclasses it, so any provider failure maps to 503 automatically |
| D3 | **Free plan = end-of-day mode**, refreshed every 30 min | Snapshots aren't on Massive's free plan (MASSIVE_API.md §1), so PLAN.md §6's "free tier: poll every 15 seconds" is impossible. Auto-detected from the first 403 |
| D4 | In end-of-day mode, a **403 for a specific date counts as "no data for that day"** | Massive's free tier refuses the current day's grouped data before it's published. Treating that as an empty day lets the trading-day walk move on instead of failing |
| D5 | **The simulator doesn't burst after a stall** | If the process is paused (laptop sleep, debugger), the fixed-cadence loop resets its schedule instead of firing hundreds of catch-up ticks at once |
| D6 | **Detection probes `AAPL` when nothing is tracked** | An empty `tickers=` parameter returns the *whole market* (10k+ rows). Never send it empty |
| D7 | **`PriceCache.version` dropped** | Nothing reads it: the SSE stream emits every tick regardless (keeps the staleness indicator green) |
| D8 | **`add_ticker` waits at most 20 s** for Massive's first load, then raises `MarketDataUnavailableError` (503) | In end-of-day mode the first load can take ~40 s (calls spaced 12 s apart on the free tier). A request shouldn't hang that long |

Items that need a matching PLAN.md update are listed in §13.

---

## 1. Overview

```
                ┌──────────────── one of ────────────────┐
                │                                         │
        ┌───────────────┐                       ┌──────────────────┐
        │SimulatorSource│ tick every 500 ms     │  MassiveSource   │ poll every 15 s (paid)
        │  (GBM engine) │                       │ (httpx, REST)    │ or EOD refresh /30 min (free)
        └───────┬───────┘                       └────────┬─────────┘
                │ cache.update(...)                      │ cache.update(...)
                └──────────────────┬─────────────────────┘
                                   ▼
                          ┌─────────────────┐
                          │   PriceCache    │  {ticker: PriceUpdate}   (in memory)
                          └────────┬────────┘
             reads only ┌──────────┼───────────┬──────────────┬───────────────┐
                        ▼          ▼           ▼              ▼               ▼
              GET /api/stream  GET /api/   trades (fill   GET /api/       LLM context
              /prices (SSE)    watchlist   price)         portfolio +
                                                          snapshot task
```

Three rules hold the design together:

1. **Sources only write the cache. Everything else only reads it.** No consumer knows which source is running.
2. **The database owns the tracked set** (watchlist ∪ open positions). The app pushes it into the source; sources never touch the DB.
3. **Everything runs on the single asyncio event loop.** No threads, so no locks. The only network I/O is `httpx.AsyncClient`.

---

## 2. Module Layout & Dependencies

```
backend/
├── pyproject.toml
├── app/
│   ├── main.py                 # FastAPI app + lifespan (§9.1)
│   ├── db.py                   # connect(), init_db(), tracked_tickers() (§9.2)
│   ├── api/                    # routers: watchlist, portfolio, chat, stream, health
│   └── market/
│       ├── __init__.py         # public API (§2.1)
│       ├── errors.py           # InvalidTickerError, UnknownTickerError, MarketDataUnavailableError
│       ├── tickers.py          # normalize_ticker()
│       ├── models.py           # PriceUpdate, format_timestamp()
│       ├── cache.py            # PriceCache
│       ├── base.py             # MarketDataSource ABC
│       ├── factory.py          # create_market_data_source()
│       ├── stream.py           # price_events() SSE generator
│       ├── simulator/
│       │   ├── __init__.py
│       │   ├── seeds.py        # TickerProfile, DEFAULT_PROFILES
│       │   ├── engine.py       # SimulatorEngine (pure math)
│       │   └── source.py       # SimulatorSource
│       └── massive/
│           ├── __init__.py
│           ├── parse.py        # pure parsing + trading-day helpers
│           ├── client.py       # MassiveClient (httpx + rate limiter)
│           └── source.py       # MassiveSource (snapshot / eod modes)
└── tests/
    └── market/                 # §12
```

### `pyproject.toml` (market-data relevant parts)

```toml
[project]
name = "trading-workstation-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",          # Massive client + FastAPI test client
    "python-dotenv>=1.0",   # PLAN.md §5
    "tzdata>=2024.1",       # zoneinfo("America/New_York") on Windows / slim images
]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

The simulator uses only the standard library (`math`, `random`). No numpy.

### 2.1 Public API: `app/market/__init__.py`

```python
from .base import MarketDataSource
from .cache import PriceCache
from .errors import InvalidTickerError, MarketDataUnavailableError, UnknownTickerError
from .factory import create_market_data_source
from .models import PriceUpdate
from .stream import price_events
from .tickers import normalize_ticker

__all__ = [
    "MarketDataSource", "PriceCache", "PriceUpdate",
    "InvalidTickerError", "UnknownTickerError", "MarketDataUnavailableError",
    "create_market_data_source", "normalize_ticker", "price_events",
]
```

Code outside `app/market/` imports **only** these names, never `simulator/` or `massive/` directly.

---

## 3. Core Types

### 3.1 `errors.py`

```python
class MarketDataError(Exception):
    """Base class for market-data errors."""


class InvalidTickerError(MarketDataError, ValueError):
    """Fails the format rule (PLAN.md §6). API → 400 "Invalid ticker"."""

    def __init__(self, raw: object) -> None:
        super().__init__("Invalid ticker")
        self.raw = raw


class UnknownTickerError(MarketDataError, LookupError):
    """Well-formed, but the source has no data for it. API → 400 "Unknown ticker: XYZ"."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"Unknown ticker: {ticker}")
        self.ticker = ticker


class MarketDataUnavailableError(MarketDataError):
    """The source can't answer right now (still loading, provider down, rate limited).
    API → 503 "Market data unavailable, try again shortly"."""
```

### 3.2 `tickers.py`

```python
import re

from .errors import InvalidTickerError

TICKER_RE = re.compile(r"[A-Z][A-Z.]{0,9}")


def normalize_ticker(raw: object) -> str:
    """Trim, uppercase and validate (PLAN.md §6 Ticker Rules).

    >>> normalize_ticker("  brk.b ")
    'BRK.B'
    """
    if not isinstance(raw, str):
        raise InvalidTickerError(raw)
    ticker = raw.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise InvalidTickerError(raw)
    return ticker
```

Normalization happens **once, at the boundary** (API route or LLM action). Sources and the cache receive already-normalized tickers.

### 3.3 `models.py`

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Direction = Literal["up", "down", "flat"]


def format_timestamp(ts: datetime) -> str:
    """ISO 8601 UTC with milliseconds and a Z suffix: 2026-01-01T12:00:00.500Z (D1)."""
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float            # rounded to 2 decimals
    previous_price: float   # price before this update (== price on the first update)
    reference_price: float  # baseline for change %: seed price (simulator) or previous close (Massive)
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
        if self.reference_price <= 0:
            return 0.0
        return round((self.price - self.reference_price) / self.reference_price * 100, 2)

    def to_dict(self) -> dict:
        """The exact field set of an SSE entry and a GET /api/watchlist row (PLAN.md §6, §8)."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": format_timestamp(self.timestamp),
            "direction": self.direction,
            "change_percent": self.change_percent,
        }
```

`direction` compares **rounded** prices, which is what the user sees, so a sub-cent move is `"flat"` and fires no flash. `reference_price` is internal and is not part of `to_dict()`.

### 3.4 `cache.py`

```python
import math
from datetime import datetime, timezone

from .models import PriceUpdate


class PriceCache:
    """Latest price per tracked ticker. Written by exactly one source, read by everyone.

    All access happens on the event loop thread, so no locking is needed.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}

    def update(
        self,
        ticker: str,
        price: float,
        reference_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> PriceUpdate:
        """Record a new price for `ticker`.

        - previous_price is the old entry's price (or the new price on the first write).
        - reference_price=None keeps the old reference; on the first write it defaults to the price.
        """
        if not (math.isfinite(price) and price > 0):
            raise ValueError(f"Invalid price for {ticker}: {price!r}")
        if reference_price is not None and not (math.isfinite(reference_price) and reference_price > 0):
            reference_price = None

        old = self._prices.get(ticker)
        price = round(price, 2)
        if reference_price is None:
            reference_price = old.reference_price if old else price

        entry = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            reference_price=reference_price,
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        self._prices[ticker] = entry
        return entry

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        entry = self._prices.get(ticker)
        return entry.price if entry else None

    def snapshot(self) -> dict[str, PriceUpdate]:
        """Shallow copy; safe to iterate while sources keep writing."""
        return dict(self._prices)

    def remove(self, ticker: str) -> None:
        self._prices.pop(ticker, None)

    def __contains__(self, ticker: object) -> bool:
        return ticker in self._prices

    def __len__(self) -> int:
        return len(self._prices)
```

Rules:

- Only the active `MarketDataSource` calls `update()` / `remove()`. Request handlers never write prices.
- The cache never invents a price. A ticker that's missing has **no price yet**, and each consumer handles that (§9.6).

**Example** of how entries chain:

```python
cache = PriceCache()
cache.update("AAPL", 190.0, reference_price=190.0)   # seed
cache.update("AAPL", 190.123)                          # tick
e = cache.get("AAPL")
# e.price == 190.12, e.previous_price == 190.0, e.reference_price == 190.0
# e.direction == "up", e.change_percent == 0.06
```

---

## 4. The Unified Interface: `base.py`

```python
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache
from .errors import MarketDataUnavailableError, UnknownTickerError

logger = logging.getLogger(__name__)


class MarketDataSource(ABC):
    """Prices a set of tracked tickers and writes them into a PriceCache."""

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin tracking `tickers` and launch the background task.
        Returns quickly (no slow network work). Called once, from the lifespan handler."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking `ticker`. When this returns, the cache HAS a price for it.
        Raises UnknownTickerError if the source can't price it,
        MarketDataUnavailableError if the source can't answer right now.
        No-op (and no network call) if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker` and remove it from the cache. No-op if not tracked."""

    @abstractmethod
    def tracked_tickers(self) -> frozenset[str]:
        """The tickers currently being priced."""

    async def sync_tickers(self, desired: Iterable[str]) -> None:
        """Make the tracked set equal `desired` (the DB's watchlist ∪ positions).

        Missing tickers are added; failures are logged, not raised, because these tickers
        are already persisted and the user shouldn't get an error for an unrelated request."""
        desired = set(desired)
        current = self.tracked_tickers()
        for ticker in current - desired:
            await self.remove_ticker(ticker)
        for ticker in desired - current:
            try:
                await self.add_ticker(ticker)
            except (UnknownTickerError, MarketDataUnavailableError) as exc:
                logger.warning("Could not track %s: %s", ticker, exc)
```

### Behaviour contract (both sources pass the same test suite, §12.5)

| # | Rule |
|---|---|
| C1 | After `await start(ts)`, every ticker in `ts` the source can price appears in the cache within one tick (simulator: immediately) or one poll (Massive) |
| C2 | After `await add_ticker(t)` returns, `t in cache` is `True` |
| C3 | `add_ticker(t)` for an already-tracked `t` returns immediately, with no network call |
| C4 | After `await remove_ticker(t)`, `t not in cache`, and the background task never writes `t` again |
| C5 | The background task survives errors: a failed tick/poll is logged, the last prices stay, the loop continues |
| C6 | `stop()` is idempotent and leaves no running task |
| C7 | A ticker's `reference_price` is stable for the life of the process (simulator) or the trading day (Massive) |
| C8 | Sources never touch the database |

**Why no locks:** the background loop and the request handlers share one event loop. A source never `await`s between reading its tracked set and writing the cache for that set, so a handler can't interleave with a half-finished write. Where an `await` is unavoidable (an HTTP call), the source re-checks membership after it (§6.4, `_apply_snapshots`).

---

## 5. The Simulator

The model is specified in [`MARKET_SIMULATOR.md`](MARKET_SIMULATOR.md) §1. In short:

```
S(t+Δt) = S(t) · exp((μ − σ²/2)·Δt + σ·√Δt·Z)          exact GBM step, never negative
Z_i     = w_m·M + w_s·S_sector(i) + w_e·ε_i             w_m² + w_s² + w_e² = 1
Δt      = 0.5 s / (252 × 6.5 × 3600 s) ≈ 8.48e-8        real-market speed (× time_scale)
event:  S ← S · (1 ± U(0.02, 0.05))  with p = 0.5/600 per ticker per tick
```

Defaults give a correlation of **0.6** within a sector, **0.3** across sectors, **0** for unknown tickers, and about **one 2–5 % event per minute** across a 10-ticker watchlist.

### 5.1 `simulator/seeds.py`

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerProfile:
    seed_price: float
    drift: float          # μ, annual
    volatility: float     # σ, annual
    sector: str | None    # None = uncorrelated with everything


DEFAULT_PROFILES: dict[str, TickerProfile] = {
    #                     seed    μ     σ     sector
    "AAPL":  TickerProfile(190.0, 0.08, 0.25, "tech"),
    "GOOGL": TickerProfile(175.0, 0.08, 0.28, "tech"),
    "MSFT":  TickerProfile(420.0, 0.08, 0.24, "tech"),
    "META":  TickerProfile(500.0, 0.10, 0.35, "tech"),
    "NVDA":  TickerProfile(130.0, 0.15, 0.50, "tech"),
    "AMD":   TickerProfile(160.0, 0.12, 0.50, "tech"),
    "AMZN":  TickerProfile(185.0, 0.10, 0.30, "consumer"),
    "TSLA":  TickerProfile(250.0, 0.10, 0.60, "consumer"),
    "NFLX":  TickerProfile(650.0, 0.10, 0.40, "consumer"),
    "DIS":   TickerProfile(100.0, 0.06, 0.28, "consumer"),
    "JPM":   TickerProfile(200.0, 0.06, 0.20, "finance"),
    "V":     TickerProfile(275.0, 0.06, 0.18, "finance"),
    "BAC":   TickerProfile(40.0,  0.06, 0.25, "finance"),
    "PYPL":  TickerProfile(70.0,  0.05, 0.40, "finance"),
}

# Unknown tickers (PLAN.md §6): random seed in [50, 300], default volatility, no sector.
UNKNOWN_PRICE_RANGE = (50.0, 300.0)
UNKNOWN_DRIFT = 0.05
UNKNOWN_VOLATILITY = 0.30
```

The first ten are PLAN.md §7's default watchlist. The other four are common additions that deserve a realistic seed and a sector (PYPL is the ticker used in PLAN.md's examples).

### 5.2 `simulator/engine.py`: pure math, no asyncio, no clock

```python
import math
import random
from dataclasses import dataclass

from .seeds import (
    DEFAULT_PROFILES,
    UNKNOWN_DRIFT,
    UNKNOWN_PRICE_RANGE,
    UNKNOWN_VOLATILITY,
    TickerProfile,
)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800


@dataclass(slots=True)
class _State:
    price: float              # full precision; rounding happens in the cache
    profile: TickerProfile


class SimulatorEngine:
    def __init__(
        self,
        rng: random.Random | None = None,
        *,
        tick_seconds: float = 0.5,
        time_scale: float = 1.0,
        market_weight: float = math.sqrt(0.3),
        sector_weight: float = math.sqrt(0.3),
        event_mean_seconds: float = 600.0,
        event_range: tuple[float, float] = (0.02, 0.05),
    ) -> None:
        if tick_seconds <= 0 or time_scale <= 0:
            raise ValueError("tick_seconds and time_scale must be > 0")
        if market_weight**2 + sector_weight**2 > 1:
            raise ValueError("market_weight² + sector_weight² must be ≤ 1")

        self.rng = rng or random.Random()
        self.dt = tick_seconds * time_scale / TRADING_SECONDS_PER_YEAR
        self._sqrt_dt = math.sqrt(self.dt)
        self.w_m = market_weight
        self.w_s = sector_weight
        self.w_e = math.sqrt(1.0 - market_weight**2 - sector_weight**2)
        self.event_prob = tick_seconds / event_mean_seconds   # inf → 0.0 (events off)
        self.event_range = event_range
        self._states: dict[str, _State] = {}

    # --- membership --------------------------------------------------------
    def add(self, ticker: str) -> float:
        """Start simulating `ticker` and return its seed price. Idempotent."""
        state = self._states.get(ticker)
        if state is not None:
            return state.price
        profile = DEFAULT_PROFILES.get(ticker) or TickerProfile(
            seed_price=round(self.rng.uniform(*UNKNOWN_PRICE_RANGE), 2),
            drift=UNKNOWN_DRIFT,
            volatility=UNKNOWN_VOLATILITY,
            sector=None,
        )
        self._states[ticker] = _State(price=profile.seed_price, profile=profile)
        return profile.seed_price

    def remove(self, ticker: str) -> None:
        self._states.pop(ticker, None)

    def tickers(self) -> frozenset[str]:
        return frozenset(self._states)

    def profile(self, ticker: str) -> TickerProfile | None:
        state = self._states.get(ticker)
        return state.profile if state else None

    # --- simulation --------------------------------------------------------
    def step(self) -> dict[str, float]:
        """Advance every ticker by one tick. Returns {ticker: new full-precision price}."""
        gauss = self.rng.gauss
        market = gauss(0.0, 1.0)
        sectors: dict[str, float] = {}
        out: dict[str, float] = {}

        for ticker, st in self._states.items():
            p = st.profile
            if p.sector is None:
                z = gauss(0.0, 1.0)
            else:
                if p.sector not in sectors:
                    sectors[p.sector] = gauss(0.0, 1.0)
                z = self.w_m * market + self.w_s * sectors[p.sector] + self.w_e * gauss(0.0, 1.0)

            st.price *= math.exp(
                (p.drift - 0.5 * p.volatility**2) * self.dt + p.volatility * self._sqrt_dt * z
            )

            if self.event_prob and self.rng.random() < self.event_prob:
                sign = 1.0 if self.rng.random() < 0.5 else -1.0
                st.price *= 1.0 + sign * self.rng.uniform(*self.event_range)

            out[ticker] = st.price
        return out
```

- The engine keeps **full-precision** prices. If it stored rounded ones, sub-cent moves would be lost each tick and low-volatility tickers would stall.
- Draw order follows dict order, which is deterministic, so a fixed `rng` seed reproduces a run exactly.

### 5.3 `simulator/source.py`

```python
import asyncio
import contextlib
import logging
import random
from collections.abc import Iterable

from ..base import MarketDataSource
from ..cache import PriceCache
from .engine import SimulatorEngine

logger = logging.getLogger(__name__)


class SimulatorSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        *,
        interval: float = 0.5,
        rng: random.Random | None = None,
        time_scale: float = 1.0,
        engine: SimulatorEngine | None = None,
    ) -> None:
        super().__init__(cache)
        self.interval = interval
        self.engine = engine or SimulatorEngine(rng, tick_seconds=interval, time_scale=time_scale)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        for ticker in tickers:
            self._seed(ticker)                     # C1: priced before the first tick
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:                       # C6
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self.engine.tickers():    # C3
            self._seed(ticker)                     # C2
        # Any well-formed ticker is accepted: the simulator never raises UnknownTickerError.

    async def remove_ticker(self, ticker: str) -> None:
        self.engine.remove(ticker)
        self.cache.remove(ticker)                  # C4

    def tracked_tickers(self) -> frozenset[str]:
        return self.engine.tickers()

    # --- internals ---------------------------------------------------------
    def _seed(self, ticker: str) -> None:
        seed = self.engine.add(ticker)
        self.cache.update(ticker, seed, reference_price=seed)   # change % starts at 0.00

    def _tick(self) -> None:
        for ticker, price in self.engine.step().items():
            self.cache.update(ticker, price)       # reference kept from the seed (C7)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                self._tick()                       # no awaits inside a tick
            except Exception:                      # C5
                logger.exception("Simulator tick failed")
            next_tick += self.interval
            now = loop.time()
            if next_tick < now:                    # D5: fell behind; don't burst
                next_tick = now
            await asyncio.sleep(next_tick - now)
```

- **Fixed cadence:** sleeping until `next_tick` keeps exactly 2 ticks per second however long a tick takes, so chart points are evenly spaced.
- **Cost:** one tick for 10–50 tickers is well under a millisecond, so it never delays the SSE streams or the API.

### 5.4 Example: what the simulator produces

```python
import random
from app.market import PriceCache
from app.market.simulator.source import SimulatorSource

cache = PriceCache()
sim = SimulatorSource(cache, rng=random.Random(7))
await sim.start(["AAPL", "TSLA"])
cache.get("AAPL").to_dict()
# {'ticker': 'AAPL', 'price': 190.0, 'previous_price': 190.0,
#  'timestamp': '2026-10-18T19:00:00.000Z', 'direction': 'flat', 'change_percent': 0.0}

await asyncio.sleep(2)              # ~4 ticks later
cache.get("AAPL").to_dict()
# {'ticker': 'AAPL', 'price': 190.03, 'previous_price': 190.01,
#  'timestamp': '2026-10-18T19:00:02.000Z', 'direction': 'up', 'change_percent': 0.02}

await sim.add_ticker("ZZZ")         # unknown → random seed in [50, 300], uncorrelated
cache.get("ZZZ").price              # e.g. 137.42
```

Typical magnitudes (1σ): AAPL ≈ $0.014 per tick and ≈ 0.6 % per hour; TSLA ≈ $0.044 per tick and ≈ 1.5 % per hour. `SimulatorSource(cache, time_scale=60)` makes each real second behave like a trading minute, for livelier demos and screenshots.

---

## 6. The Massive Source

### 6.1 Two modes, auto-detected

| | `snapshot` mode | `eod` mode |
|---|---|---|
| Plans | Starter, Developer, Advanced | Basic (free) |
| Endpoint | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=A,B,…` | `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` |
| Calls | **1 per poll**, all tracked tickers | ~3 per refresh, returns the whole market |
| Interval | `MASSIVE_POLL_INTERVAL` (default 15 s) | every 30 min |
| Price | `lastTrade.p` → `min.c` → `day.c` → `prevDay.c` (first value > 0) | latest trading day's close |
| Reference | `prevDay.c` (previous close) | the trading day before's close |
| Timestamp | snapshot `updated` (ns) | 16:00 New York time on the latest trading day |
| Add a ticker | 1 snapshot call for that ticker | **0 calls**: look it up in the in-memory map |
| Rate limiting | none needed | calls spaced **≥ 12 s** apart (5/min) |

**Detection** (first iteration of the background loop, unless `MASSIVE_MODE` forces a mode):

```
snapshot call for the tracked tickers (or ["AAPL"] if none, D6)
  ├─ 200          → snapshot mode; apply the prices; ready
  ├─ 403          → eod mode; load the last two trading days; ready
  └─ other error  → stay undetected; retry after the backoff
```

In `eod` mode the price only changes when a new trading day is published, so every SSE event reports `direction: "flat"`. That's accurate for the data available. The simulator remains the default and the better demo.

### 6.2 `massive/parse.py`: pure functions

```python
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class ParsedPrice:
    price: float
    reference: float | None
    timestamp: datetime


def _positive(value: object) -> float | None:
    """float(value) if it's a finite number > 0, else None (Massive uses 0 for 'missing')."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def ns_to_datetime(ns: object) -> datetime | None:
    if isinstance(ns, bool) or not isinstance(ns, (int, float)) or ns <= 0:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def parse_snapshot(snap: dict, now: datetime | None = None) -> ParsedPrice | None:
    """One element of the snapshot `tickers[]` array → price, reference, timestamp.

    Returns None when no usable price exists (e.g. the 3:30–4:00 AM ET daily reset)."""

    def field(obj: str, key: str) -> float | None:
        return _positive((snap.get(obj) or {}).get(key))

    price = (
        field("lastTrade", "p")
        or field("min", "c")
        or field("day", "c")
        or field("prevDay", "c")
    )
    if price is None:
        return None
    timestamp = ns_to_datetime(snap.get("updated")) or now or datetime.now(timezone.utc)
    return ParsedPrice(price=price, reference=field("prevDay", "c"), timestamp=timestamp)


def parse_grouped(data: dict) -> dict[str, float]:
    """Grouped-daily response → {ticker: close}. Empty dict for a day with no data."""
    closes: dict[str, float] = {}
    for row in data.get("results") or []:
        ticker, close = row.get("T"), _positive(row.get("c"))
        if isinstance(ticker, str) and close is not None:
            closes[ticker] = close
    return closes


# --- trading-day helpers ----------------------------------------------------
def last_weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:            # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d


def previous_weekday(d: date) -> date:
    return last_weekday_on_or_before(d - timedelta(days=1))


def market_close_utc(d: date) -> datetime:
    """16:00 New York time on `d`, as UTC (handles daylight saving)."""
    return datetime.combine(d, time(16, 0), tzinfo=NY).astimezone(timezone.utc)
```

**Example:**

```python
parse_snapshot({
    "ticker": "AAPL",
    "min": {"c": 190.5},
    "day": {"c": 190.4},
    "prevDay": {"c": 188.0},
    "lastTrade": {"p": 0},          # missing on Starter → zero → skipped
    "updated": 1_700_000_000_000_000_000,
})
# ParsedPrice(price=190.5, reference=188.0,
#             timestamp=datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc))
```

### 6.3 `massive/client.py`: thin async HTTP layer

```python
import asyncio
import time
from collections.abc import Iterable
from datetime import date

import httpx

from ..errors import MarketDataUnavailableError
from .parse import parse_grouped

BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
GROUPED_PATH = "/v2/aggs/grouped/locale/us/market/stocks/{day}"


class MassiveError(MarketDataUnavailableError):
    """Any failure talking to Massive. Subclass of MarketDataUnavailableError → 503 (D2)."""


class MassiveAuthError(MassiveError):        # 401: missing / invalid key
    pass


class PlanNotEntitledError(MassiveError):    # 403: endpoint or date not in the plan
    pass


class RateLimitedError(MassiveError):        # 429
    pass


class MassiveClient:
    """Only the two endpoints the app needs. No automatic retries: the next poll is the retry."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        min_interval: float = 0.0,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self.min_interval = min_interval     # seconds between calls; 12.0 on the free plan
        self._last_call: float | None = None
        self._spacing = asyncio.Lock()
        self.calls = 0                       # handy for logs and tests

    async def snapshots(self, tickers: Iterable[str]) -> dict[str, dict]:
        """Paid plans. {ticker: raw snapshot}. Unknown tickers are simply absent."""
        wanted = sorted(set(tickers))
        if not wanted:                       # D6: an empty filter means "whole market"
            return {}
        data = await self._get(SNAPSHOT_PATH, {"tickers": ",".join(wanted)})
        return {s["ticker"]: s for s in data.get("tickers") or [] if isinstance(s, dict) and s.get("ticker")}

    async def grouped_daily(self, day: date) -> dict[str, float]:
        """All plans. {ticker: close} for every US stock on `day`; {} if no data."""
        data = await self._get(GROUPED_PATH.format(day=day.isoformat()), {"adjusted": "true"})
        return parse_grouped(data)

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- internals ---------------------------------------------------------
    async def _wait_for_slot(self) -> None:
        async with self._spacing:
            if self.min_interval and self._last_call is not None:
                wait = self._last_call + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        await self._wait_for_slot()
        self.calls += 1
        try:
            resp = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:       # timeouts, DNS, connection resets
            raise MassiveError(f"Massive request failed: {type(exc).__name__}") from exc

        status = resp.status_code
        if status == 401:
            raise MassiveAuthError("Massive rejected the API key (401)")
        if status == 403:
            raise PlanNotEntitledError(f"Massive plan does not include {path} (403)")
        if status == 429:
            raise RateLimitedError("Massive rate limit exceeded (429)")
        if status >= 400:
            raise MassiveError(f"Massive returned HTTP {status} for {path}")
        try:
            return resp.json()
        except ValueError as exc:
            raise MassiveError("Massive returned invalid JSON") from exc
```

- The key goes only in the `Authorization` header, so it never appears in URLs, logs or exception messages.
- Branch on the **status code only**, never the message text (MASSIVE_API.md §3).
- The spacing lock reserves a time slot and releases it before the request, so slow responses don't hold other callers up.

### 6.4 `massive/source.py`

```python
import asyncio
import contextlib
import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Literal

import httpx

from ..base import MarketDataSource
from ..cache import PriceCache
from ..errors import MarketDataUnavailableError, UnknownTickerError
from .client import (
    BASE_URL,
    MassiveClient,
    MassiveError,
    PlanNotEntitledError,
    RateLimitedError,
)
from .parse import NY, last_weekday_on_or_before, market_close_utc, parse_snapshot, previous_weekday

logger = logging.getLogger(__name__)

Mode = Literal["snapshot", "eod"]
PROBE_TICKER = "AAPL"


class MassiveSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        *,
        mode: Mode | None = None,            # None = auto-detect
        poll_interval: float = 15.0,         # snapshot mode
        eod_refresh: float = 1800.0,         # eod mode
        error_backoff: float = 60.0,         # after 429s and eod failures
        free_tier_spacing: float = 12.0,     # 5 calls/min
        ready_timeout: float = 20.0,         # D8
        eod_max_calls: int = 5,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(cache)
        if mode not in (None, "snapshot", "eod"):
            raise ValueError(f"Invalid Massive mode: {mode!r}")
        self._api_key = api_key
        self._mode: Mode | None = mode
        self._poll_interval = poll_interval
        self._eod_refresh = eod_refresh
        self._error_backoff = error_backoff
        self._free_tier_spacing = free_tier_spacing
        self._ready_timeout = ready_timeout
        self._eod_max_calls = eod_max_calls
        self._base_url = base_url
        self._transport = transport
        self._today = today or (lambda: datetime.now(NY).date())

        self._tickers: set[str] = set()
        self._latest: dict[str, float] = {}      # eod: whole-market closes, latest day
        self._previous: dict[str, float] = {}    # eod: whole-market closes, day before
        self._latest_day: date | None = None
        self._ready = asyncio.Event()            # set after the first successful load
        self._client: MassiveClient | None = None
        self._task: asyncio.Task | None = None

    @property
    def mode(self) -> Mode | None:
        return self._mode

    @property
    def client(self) -> MassiveClient:
        if self._client is None:
            raise RuntimeError("MassiveSource.start() has not been called")
        return self._client

    # --- MarketDataSource ----------------------------------------------------
    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers = set(tickers)
        spacing = 0.0 if self._mode == "snapshot" else self._free_tier_spacing
        self._client = MassiveClient(
            self._api_key, base_url=self._base_url, transport=self._transport, min_interval=spacing
        )
        self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:                              # C3
            return
        if self._mode is None or (self._mode == "eod" and self._latest_day is None):
            await self._wait_ready()

        if self._mode == "snapshot":
            snaps = await self.client.snapshots([ticker])        # 1 call
            parsed = parse_snapshot(snaps[ticker]) if ticker in snaps else None
            if parsed is None:
                raise UnknownTickerError(ticker)
            self.cache.update(ticker, parsed.price, parsed.reference, parsed.timestamp)
        else:
            if ticker not in self._latest:                       # 0 calls
                raise UnknownTickerError(ticker)
            self._write_eod(ticker)
        self._tickers.add(ticker)                                # C2: cache already seeded

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self.cache.remove(ticker)                                # C4

    def tracked_tickers(self) -> frozenset[str]:
        return frozenset(self._tickers)

    # --- background loop -------------------------------------------------------
    async def _run(self) -> None:
        while True:
            try:
                await self._poll_once()
                delay = self._eod_refresh if self._mode == "eod" else self._poll_interval
            except asyncio.CancelledError:
                raise
            except RateLimitedError:
                logger.warning("Massive rate limit hit; backing off %.0fs", self._error_backoff)
                delay = self._error_backoff
            except Exception as exc:                             # C5
                if isinstance(exc, MassiveError):
                    logger.error("Massive poll failed: %s. Keeping last prices.", exc)
                else:
                    logger.exception("Massive poll failed unexpectedly. Keeping last prices.")
                delay = self._error_backoff if self._mode == "eod" else self._poll_interval
            await asyncio.sleep(delay)

    async def _poll_once(self) -> None:
        if self._mode is None:
            await self._detect_mode()
        elif self._mode == "snapshot":
            await self._poll_snapshot()
        else:
            await self._refresh_eod()

    async def _detect_mode(self) -> None:
        probe = sorted(self._tickers) or [PROBE_TICKER]          # D6
        try:
            snaps = await self.client.snapshots(probe)
        except PlanNotEntitledError:
            logger.warning(
                "Massive plan has no snapshot access; using end-of-day prices "
                "(refreshed every %.0f min)", self._eod_refresh / 60
            )
            self._mode = "eod"
            await self._refresh_eod()
            return
        self._mode = "snapshot"
        self.client.min_interval = 0.0                           # paid plans are unlimited
        logger.info("Massive snapshot mode: polling every %.0fs", self._poll_interval)
        self._apply_snapshots(snaps)
        self._ready.set()

    async def _poll_snapshot(self) -> None:
        tickers = frozenset(self._tickers)
        if tickers:
            self._apply_snapshots(await self.client.snapshots(tickers))
        self._ready.set()

    def _apply_snapshots(self, snaps: dict[str, dict]) -> None:
        for ticker, snap in snaps.items():
            if ticker not in self._tickers:                      # removed during the await (C4)
                continue
            parsed = parse_snapshot(snap)
            if parsed is not None:                               # else keep the last price
                self.cache.update(ticker, parsed.price, parsed.reference, parsed.timestamp)

    # --- eod mode ----------------------------------------------------------------
    async def _refresh_eod(self) -> None:
        (latest_day, latest), previous = await self._latest_two_closes()
        self._latest, self._previous, self._latest_day = latest, previous, latest_day
        for ticker in frozenset(self._tickers):                  # no awaits in this loop
            if ticker in latest:
                self._write_eod(ticker)
            else:
                logger.warning("No end-of-day data for tracked ticker %s", ticker)
        self._ready.set()
        logger.info("Massive end-of-day prices loaded for %s", latest_day.isoformat())

    async def _latest_two_closes(self) -> tuple[tuple[date, dict[str, float]], dict[str, float]]:
        """Walk back from today: weekends are skipped for free; holidays, unpublished days
        and 403s for not-yet-available dates (D4) cost one call each and are skipped."""
        day = last_weekday_on_or_before(self._today())
        found: list[tuple[date, dict[str, float]]] = []
        for _ in range(self._eod_max_calls):
            try:
                closes = await self.client.grouped_daily(day)
            except PlanNotEntitledError:
                closes = {}
            if closes:
                found.append((day, closes))
                if len(found) == 2:
                    return found[0], found[1][1]
            day = previous_weekday(day)
        raise MassiveError("Could not find two trading days of end-of-day data")

    def _write_eod(self, ticker: str) -> None:
        assert self._latest_day is not None
        self.cache.update(
            ticker,
            self._latest[ticker],
            self._previous.get(ticker),
            market_close_utc(self._latest_day),
        )

    async def _wait_ready(self) -> None:
        try:
            await asyncio.wait_for(self._ready.wait(), self._ready_timeout)
        except TimeoutError:
            raise MarketDataUnavailableError("Market data is still loading") from None
```

### 6.5 API-call budget

| Situation | Calls | Notes |
|---|---|---|
| Paid, steady state | 1 every 15 s | Independent of the number of tickers |
| Paid, add a ticker | +1 | Validates and seeds in one call |
| Free, startup | 3 (typically) | 1 snapshot probe (403) + 2 grouped-daily; ~24 s with 12 s spacing |
| Free, startup on a Monday morning before publish | 4 | Probe + today (empty/403) + Friday + Thursday |
| Free, every 30 min | 2–3 | Re-walks from today; picks up the new day once it's published |
| Free, add a ticker | **0** | Looked up in the in-memory whole-market map |

`MASSIVE_MODE=eod` skips the probe on a free key (saves 1 call and 12 s at startup).

### 6.6 Timeline example (free key, Sunday 2026-10-18)

```
t=0s   start(["AAPL", ..., "NFLX"])          → task starts, cache empty, start() returns
t=0s   GET snapshot?tickers=AAPL,...         → 403  → mode = eod
t=12s  GET grouped/2026-10-16 (Friday)       → 200, 10,812 rows
t=24s  GET grouped/2026-10-15 (Thursday)     → 200, 10,790 rows
t=24s  cache: AAPL 191.00 (ref 189.00, +1.06%), ... ; ready
t=60s  POST /api/watchlist {"ticker":"pypl"} → normalize → "PYPL" in map → seeded, 0 calls
t=30m  refresh: 10-16, 10-15 again           → unchanged values, same timestamps
```

Before `t=24s`, `GET /api/watchlist` shows `null` prices, the SSE events are `{}`, a trade returns 400 "No price available for AAPL yet", and an add waits for readiness (up to 20 s), then returns 503.

---

## 7. The Factory: `factory.py`

```python
import logging
import os
from collections.abc import Mapping

from .base import MarketDataSource
from .cache import PriceCache
from .massive.source import MassiveSource
from .simulator.source import SimulatorSource

logger = logging.getLogger(__name__)


def _float_env(env: Mapping[str, str], name: str, default: float, minimum: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring %s=%r (not a number); using %s", name, raw, default)
        return default
    return max(value, minimum)


def create_market_data_source(cache: PriceCache, env: Mapping[str, str] = os.environ) -> MarketDataSource:
    api_key = env.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        logger.info("Market data source: simulator")
        return SimulatorSource(cache)

    mode = env.get("MASSIVE_MODE", "").strip().lower() or None
    if mode not in (None, "snapshot", "eod"):
        logger.warning("Ignoring MASSIVE_MODE=%r; auto-detecting", mode)
        mode = None
    interval = _float_env(env, "MASSIVE_POLL_INTERVAL", 15.0, minimum=2.0)

    logger.info("Market data source: Massive API (mode=%s)", mode or "auto")
    return MassiveSource(cache, api_key, mode=mode, poll_interval=interval)  # type: ignore[arg-type]
```

Passing `env` as a parameter makes the factory testable with a plain dict.

---

## 8. The SSE Stream

### 8.1 `stream.py`

```python
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

from .cache import PriceCache


class _Disconnectable(Protocol):
    async def is_disconnected(self) -> bool: ...


async def price_events(
    cache: PriceCache, request: _Disconnectable, interval: float = 0.5
) -> AsyncIterator[str]:
    """PLAN.md §6: one unnamed event per tick, all tracked tickers keyed by ticker."""
    yield "retry: 2000\n\n"                      # browser reconnect delay after a drop
    while not await request.is_disconnected():
        payload = {ticker: entry.to_dict() for ticker, entry in cache.snapshot().items()}
        yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        await asyncio.sleep(interval)
```

### 8.2 The route

```python
# app/api/stream.py
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.market import price_events

router = APIRouter()


@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    return StreamingResponse(
        price_events(request.app.state.price_cache, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- It emits **every 500 ms, even when nothing changed.** That keeps the frontend's "no event for 5 s → yellow" rule green while Massive only changes every 15 s (or once a day).
- Tickers with no price are simply absent from the cache, so they're omitted (PLAN.md §6). An empty cache sends `data: {}`.
- No per-client server state: many tabs just mean many generators reading the same cache.
- **Don't add `GZipMiddleware`**: it buffers the response and breaks streaming.

**Example events** on the wire:

```text
retry: 2000

data: {"AAPL":{"ticker":"AAPL","price":190.12,"previous_price":190.05,"timestamp":"2026-10-18T19:00:01.500Z","direction":"up","change_percent":0.06},"TSLA":{"ticker":"TSLA","price":249.71,"previous_price":249.76,"timestamp":"2026-10-18T19:00:01.500Z","direction":"down","change_percent":-0.12}}

data: {"AAPL":{"ticker":"AAPL","price":190.12,"previous_price":190.12,"timestamp":"2026-10-18T19:00:02.000Z","direction":"flat","change_percent":0.06},"TSLA":{...}}
```

Try it with `curl -N http://localhost:8000/api/stream/prices`.

### 8.3 Notes for the frontend agent

- **Flash on a change of `price`** versus the last value the frontend saw for that ticker, not on `direction` alone. With Massive, the same entry (same `direction: "up"`) is re-sent for 15 s.
- **Append a chart/sparkline point only when `timestamp` changes** for that ticker. Otherwise one 15-second Massive poll becomes 30 identical points. With the simulator, every tick has a new timestamp, so the rule is harmless.
- Timestamps have millisecond precision (D1). Lightweight Charts needs strictly increasing times, so convert with `Date.parse(ts) / 1000` and drop a point whose time isn't greater than the previous one.

---

## 9. Integration With the App

### 9.1 Lifespan (`app/main.py`)

PLAN.md §7: database first, then market data, then the snapshot task.

```python
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app import db
from app.market import PriceCache, create_market_data_source

PROJECT_ROOT = Path(__file__).resolve().parents[2]      # backend/app/main.py → project root
load_dotenv(PROJECT_ROOT / ".env", override=False)       # PLAN.md §5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()                                         # schema + seed
    cache = PriceCache()
    market = create_market_data_source(cache)
    with db.connect() as conn:
        await market.start(db.tracked_tickers(conn))     # watchlist ∪ open positions
    app.state.price_cache = cache
    app.state.market = market
    snapshot_task = asyncio.create_task(portfolio_snapshot_loop(app), name="portfolio-snapshots")
    try:
        yield
    finally:
        snapshot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await snapshot_task
        await market.stop()


app = FastAPI(lifespan=lifespan)
# register_market_error_handlers(app)  (§9.3), then the /api routers, then the static mount (PLAN.md §11)
```

The portfolio snapshot at startup (PLAN.md §7) values positions with cached prices. With the simulator they're seeded synchronously by `start()`. With Massive the cache is still empty at that moment, so valuation falls back to `avg_cost` (§9.6). The next 30-second snapshot uses live prices.

### 9.2 `db.tracked_tickers()`

```python
def tracked_tickers(conn: sqlite3.Connection, user_id: str = "default") -> set[str]:
    """PLAN.md §6 Tracked Tickers: watchlist ∪ tickers with an open position."""
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? "
        "UNION SELECT ticker FROM positions WHERE user_id = ?",
        (user_id, user_id),
    ).fetchall()
    return {row[0] for row in rows}


async def resync_market(app) -> None:
    """Call after anything that can shrink the tracked set."""
    with connect() as conn:
        desired = tracked_tickers(conn)
    await app.state.market.sync_tickers(desired)
```

### 9.3 Error mapping

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.market import InvalidTickerError, MarketDataUnavailableError, UnknownTickerError


def register_market_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidTickerError)
    async def _invalid(_: Request, exc: InvalidTickerError):
        return JSONResponse(status_code=400, content={"detail": "Invalid ticker"})

    @app.exception_handler(UnknownTickerError)
    async def _unknown(_: Request, exc: UnknownTickerError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})   # "Unknown ticker: XYZ"

    @app.exception_handler(MarketDataUnavailableError)
    async def _unavailable(_: Request, exc: MarketDataUnavailableError):
        # Fixed text: the provider's error details stay in the server log.
        return JSONResponse(status_code=503, content={"detail": "Market data unavailable, try again shortly"})
```

In the **chat flow**, the same exceptions are caught per action and recorded as `{"status": "failed", "error": str(exc)}` (PLAN.md §8 `POST /api/chat`), so one bad ticker doesn't affect the others.

### 9.4 Watchlist routes

```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.market import PriceCache, normalize_ticker

router = APIRouter()


class TickerIn(BaseModel):
    ticker: str


def watchlist_payload(cache: PriceCache) -> list[dict]:
    with db.connect() as conn:
        tickers = [r[0] for r in conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = 'default' ORDER BY added_at, ticker")]
    rows = []
    for t in tickers:
        entry = cache.get(t)
        rows.append(entry.to_dict() if entry else {
            "ticker": t, "price": None, "previous_price": None,
            "timestamp": None, "direction": None, "change_percent": None,
        })
    return rows


@router.get("/api/watchlist")
async def get_watchlist(request: Request):
    return watchlist_payload(request.app.state.price_cache)


@router.post("/api/watchlist")
async def add_to_watchlist(body: TickerIn, request: Request):
    ticker = normalize_ticker(body.ticker)               # 400 "Invalid ticker"
    await request.app.state.market.add_ticker(ticker)    # validates + seeds; 400 unknown / 503
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO watchlist (user_id, ticker, added_at) VALUES ('default', ?, ?) "
            "ON CONFLICT(user_id, ticker) DO NOTHING",   # idempotent (PLAN.md §8)
            (ticker, db.now_iso()),
        )
    return watchlist_payload(request.app.state.price_cache)


@router.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    ticker = normalize_ticker(ticker)
    with db.connect() as conn:
        deleted = conn.execute(
            "DELETE FROM watchlist WHERE user_id = 'default' AND ticker = ?", (ticker,)
        ).rowcount
    if not deleted:
        raise HTTPException(404, f"{ticker} is not in the watchlist")
    await db.resync_market(request.app)                  # keeps it tracked if still held
    return watchlist_payload(request.app.state.price_cache)
```

Order matters on add: **validate and seed first, then insert**, so an unknown ticker is never persisted, and the response already includes its price.

### 9.5 Trades

```python
async def execute_trade(app, ticker: str, side: str, quantity: float) -> dict:
    ticker = normalize_ticker(ticker)
    if side == "buy" and not db.is_watched(ticker):
        await ensure_watched(app, ticker)                # same as POST /api/watchlist (PLAN.md §8)

    cache: PriceCache = app.state.price_cache
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        price = cache.get_price(ticker)                  # fill price, read inside the lock
        if price is None:
            conn.rollback()
            raise HTTPException(400, f"No price available for {ticker} yet")
        ...                                              # validate, update cash/position, log trade, snapshot
        conn.commit()

    if side == "sell" and position_closed:
        await db.resync_market(app)                      # untracks it if not watched
    ...
```

Reading the cache inside `BEGIN IMMEDIATE` costs nothing (it's a dict lookup) and fills at the price current when the write lock was taken.

### 9.6 Who reads what

| Consumer | Reads | When there's no price |
|---|---|---|
| `GET /api/stream/prices` | `cache.snapshot()` every 500 ms | Ticker omitted |
| `GET /api/watchlist` | `cache.get(t)` per row | `null` fields |
| Trades (manual and LLM) | `cache.get_price(t)` | 400 `"No price available for XYZ yet"` |
| `GET /api/portfolio`, snapshot task | `cache.get_price(t)` per position | Value at `avg_cost`, so valuations never crash |
| LLM context | `cache.snapshot()` | Listed as "no price yet" |

### 9.7 What changes the tracked set

| Event | Market call |
|---|---|
| Startup | `start(tracked_tickers)` |
| `POST /api/watchlist` | `add_ticker(t)` **before** the insert |
| `DELETE /api/watchlist/{t}` | `resync_market` after the delete |
| Buy of an unwatched ticker | `add_ticker(t)` + watchlist insert, then the trade |
| Sell to zero | `resync_market` after the commit |
| Chat actions | The same calls, with `watchlist_changes` before `trades` |

---

## 10. Configuration

| Env var | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | Empty → simulator. Set → `MassiveSource` |
| `MASSIVE_MODE` | auto | `snapshot` or `eod` skips plan detection. Invalid values are ignored with a warning |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between snapshot polls (paid plans). Minimum 2 |

Simulator tuning (`time_scale`, weights, event rate) stays in code, not in env vars.

**Startup log examples:**

```text
INFO app.market.factory: Market data source: simulator
```

```text
INFO app.market.factory: Market data source: Massive API (mode=auto)
INFO app.market.massive.source: Massive snapshot mode: polling every 15s
```

```text
INFO app.market.factory: Market data source: Massive API (mode=auto)
WARNING app.market.massive.source: Massive plan has no snapshot access; using end-of-day prices (refreshed every 30 min)
INFO app.market.massive.source: Massive end-of-day prices loaded for 2026-10-16
```

---

## 11. End-to-End Examples

### 11.1 Simulator session

```bash
$ curl -s localhost:8000/api/watchlist | jq '.[0]'
{"ticker":"AAPL","price":190.07,"previous_price":190.05,"timestamp":"2026-10-18T19:00:03.500Z","direction":"up","change_percent":0.04}

$ curl -s -X POST localhost:8000/api/watchlist -H 'content-type: application/json' -d '{"ticker":" pypl "}' | jq '.[-1]'
{"ticker":"PYPL","price":70.0,"previous_price":70.0,"timestamp":"2026-10-18T19:00:04.120Z","direction":"flat","change_percent":0.0}

$ curl -s -X POST localhost:8000/api/watchlist -H 'content-type: application/json' -d '{"ticker":"12AB"}'
{"detail":"Invalid ticker"}                                   # 400

$ curl -s -X DELETE localhost:8000/api/watchlist/IBM
{"detail":"IBM is not in the watchlist"}                      # 404
```

### 11.2 Massive (paid) session

```bash
$ curl -s -X POST localhost:8000/api/watchlist -H 'content-type: application/json' -d '{"ticker":"QWERTY"}'
{"detail":"Unknown ticker: QWERTY"}                           # 400: absent from the snapshot

# Provider down or key revoked while adding:
{"detail":"Market data unavailable, try again shortly"}       # 503
```

### 11.3 Held ticker removed from the watchlist

```
watchlist: AAPL, TSLA        positions: TSLA 5 sh
DELETE /api/watchlist/TSLA   → row deleted → resync: desired = {AAPL, TSLA} → TSLA still tracked
                               SSE keeps TSLA, the portfolio stays valued, the watchlist panel drops it
sell 5 TSLA                  → position deleted → resync: desired = {AAPL} → TSLA removed from cache/SSE
```

---

## 12. Testing

Layout:

```
backend/tests/market/
├── conftest.py               # fakes + helpers
├── test_core.py              # tickers, models, cache
├── test_engine.py            # simulator math
├── test_contract.py          # C1–C6 for both sources
├── test_massive_parse.py
├── test_massive_client.py
├── test_massive_source.py    # modes, detection, eod walk
├── test_stream.py
└── test_factory.py
```

Run with `cd backend && uv run pytest`. No network, no real sleeps longer than ~0.2 s.

### 12.1 `conftest.py`

```python
import asyncio
import time

import httpx

from app.market.massive.client import SNAPSHOT_PATH

FAKE_PRICES = {"AAPL": 190.0, "MSFT": 420.0, "PYPL": 70.0}


def make_snapshot(ticker: str, price: float) -> dict:
    return {
        "ticker": ticker,
        "min": {"c": price},
        "prevDay": {"c": round(price * 0.99, 2)},
        "updated": time.time_ns(),
    }


class FakeMassive:
    """httpx.MockTransport handler. Records every request; can fail the next N calls."""

    def __init__(self, prices: dict[str, float] | None = None, days: dict[str, dict[str, float]] | None = None,
                 snapshot_status: int = 200, forbidden_days: set[str] = frozenset()):
        self.prices = dict(prices or FAKE_PRICES)
        self.days = days or {}
        self.snapshot_status = snapshot_status
        self.forbidden_days = set(forbidden_days)
        self.requests: list[httpx.Request] = []
        self.fail_next = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(500, json={"status": "ERROR"})
        if request.url.path == SNAPSHOT_PATH:
            if self.snapshot_status != 200:
                return httpx.Response(self.snapshot_status, json={"status": "NOT_AUTHORIZED"})
            wanted = request.url.params.get("tickers", "").split(",")
            rows = [make_snapshot(t, self.prices[t]) for t in wanted if t in self.prices]
            return httpx.Response(200, json={"status": "OK", "count": len(rows), "tickers": rows})
        if "/v2/aggs/grouped/" in request.url.path:
            day = request.url.path.rsplit("/", 1)[-1]
            if day in self.forbidden_days:
                return httpx.Response(403, json={"status": "NOT_AUTHORIZED"})
            rows = [{"T": t, "c": c} for t, c in self.days.get(day, {}).items()]
            return httpx.Response(200, json={"status": "OK", "resultsCount": len(rows), "results": rows})
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


async def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)
```

### 12.2 `test_core.py`

```python
from datetime import datetime, timezone

import pytest

from app.market import InvalidTickerError, PriceCache, normalize_ticker
from app.market.models import PriceUpdate, format_timestamp


@pytest.mark.parametrize("raw, expected", [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("V", "V")])
def test_normalize_ok(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "1ABC", ".AB", "TOOLONGTICKER", "AA-PL", None, 5])
def test_normalize_rejects(raw):
    with pytest.raises(InvalidTickerError, match="Invalid ticker"):
        normalize_ticker(raw)


def test_timestamp_format_has_millis_and_z():
    ts = datetime(2026, 1, 1, 12, 0, 0, 500_000, tzinfo=timezone.utc)
    assert format_timestamp(ts) == "2026-01-01T12:00:00.500Z"


def test_direction_and_change_percent():
    u = PriceUpdate("AAPL", 191.9, 190.0, 190.0, datetime.now(timezone.utc))
    assert u.direction == "up"
    assert u.change_percent == 1.0
    assert set(u.to_dict()) == {"ticker", "price", "previous_price", "timestamp", "direction", "change_percent"}


def test_cache_chains_previous_and_keeps_reference():
    cache = PriceCache()
    first = cache.update("AAPL", 190.0, reference_price=190.0)
    assert first.previous_price == 190.0 and first.direction == "flat"
    second = cache.update("AAPL", 189.504)
    assert second.price == 189.5 and second.previous_price == 190.0
    assert second.reference_price == 190.0 and second.direction == "down"


def test_cache_sub_cent_move_is_flat():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert cache.update("AAPL", 190.004).direction == "flat"


def test_cache_rejects_bad_price_and_removes():
    cache = PriceCache()
    with pytest.raises(ValueError):
        cache.update("AAPL", 0.0)
    cache.update("AAPL", 1.0)
    cache.remove("AAPL")
    assert "AAPL" not in cache and cache.get_price("AAPL") is None
```

### 12.3 `test_engine.py`

```python
import math
import random
import statistics

from app.market.simulator.engine import SimulatorEngine

NO_EVENTS = math.inf


def log_returns(engine: SimulatorEngine, tickers: list[str], steps: int) -> dict[str, list[float]]:
    prev = {t: engine.add(t) for t in tickers}
    series = {t: [] for t in tickers}
    for _ in range(steps):
        prices = engine.step()
        for t in tickers:
            series[t].append(math.log(prices[t] / prev[t]))
            prev[t] = prices[t]
    return series


def test_seeds():
    e = SimulatorEngine(random.Random(1))
    assert e.add("AAPL") == 190.0
    seed = e.add("ZZZ")
    assert 50.0 <= seed <= 300.0
    assert e.profile("ZZZ").sector is None and e.profile("ZZZ").volatility == 0.30
    assert e.add("ZZZ") == seed                       # idempotent


def test_prices_stay_positive_with_frequent_events():
    e = SimulatorEngine(random.Random(2), event_mean_seconds=5.0)
    for t in ["AAPL", "TSLA", "ZZZ"]:
        e.add(t)
    for _ in range(20_000):
        assert all(p > 0 for p in e.step().values())


def test_volatility_matches_gbm():
    e = SimulatorEngine(random.Random(3), event_mean_seconds=NO_EVENTS)
    r = log_returns(e, ["AAPL"], 20_000)["AAPL"]
    expected = 0.25 * math.sqrt(e.dt)
    assert abs(statistics.stdev(r) / expected - 1) < 0.03


def test_correlations():
    e = SimulatorEngine(random.Random(4), event_mean_seconds=NO_EVENTS)
    r = log_returns(e, ["AAPL", "MSFT", "JPM", "ZZZ"], 20_000)
    assert abs(statistics.correlation(r["AAPL"], r["MSFT"]) - 0.6) < 0.05   # same sector
    assert abs(statistics.correlation(r["AAPL"], r["JPM"]) - 0.3) < 0.05    # cross sector
    assert abs(statistics.correlation(r["AAPL"], r["ZZZ"])) < 0.05          # unknown


def test_event_size():
    e = SimulatorEngine(random.Random(5), event_mean_seconds=0.5)          # event every tick
    prev = e.add("AAPL")
    for _ in range(500):
        price = e.step()["AAPL"]
        assert 0.0195 <= abs(price / prev - 1) <= 0.0505
        prev = price


def test_deterministic():
    paths = []
    for _ in range(2):
        e = SimulatorEngine(random.Random(42))
        e.add("AAPL"); e.add("ZZZ")
        paths.append([e.step() for _ in range(100)])
    assert paths[0] == paths[1]


def test_time_scale():
    base = SimulatorEngine(random.Random(6), event_mean_seconds=NO_EVENTS)
    fast = SimulatorEngine(random.Random(6), event_mean_seconds=NO_EVENTS, time_scale=60)
    s1 = statistics.stdev(log_returns(base, ["AAPL"], 10_000)["AAPL"])
    s2 = statistics.stdev(log_returns(fast, ["AAPL"], 10_000)["AAPL"])
    assert abs(s2 / s1 / math.sqrt(60) - 1) < 0.05
```

### 12.4 `test_massive_parse.py`

```python
from datetime import date, datetime, timezone

from app.market.massive.parse import (
    last_weekday_on_or_before, market_close_utc, parse_grouped, parse_snapshot, previous_weekday,
)


def test_fallback_chain():
    assert parse_snapshot({"lastTrade": {"p": 10.0}, "min": {"c": 9.0}}).price == 10.0
    assert parse_snapshot({"lastTrade": {"p": 0}, "min": {"c": 9.0}}).price == 9.0
    assert parse_snapshot({"day": {"c": 8.0}, "prevDay": {"c": 7.0}}).price == 8.0
    only_prev = parse_snapshot({"day": {"c": 0}, "prevDay": {"c": 7.0}})
    assert only_prev.price == 7.0 and only_prev.reference == 7.0


def test_nothing_usable():
    assert parse_snapshot({"ticker": "X", "day": {"c": 0}}) is None


def test_ns_timestamp():
    p = parse_snapshot({"min": {"c": 1.0}, "updated": 1_700_000_000_000_000_000})
    assert p.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def test_parse_grouped_skips_bad_rows():
    data = {"results": [{"T": "AAPL", "c": 190.0}, {"T": "BAD", "c": 0}, {"c": 5.0}]}
    assert parse_grouped(data) == {"AAPL": 190.0}
    assert parse_grouped({"resultsCount": 0}) == {}


def test_trading_days():
    assert last_weekday_on_or_before(date(2026, 10, 18)) == date(2026, 10, 16)   # Sun → Fri
    assert previous_weekday(date(2026, 10, 19)) == date(2026, 10, 16)            # Mon → Fri
    assert market_close_utc(date(2026, 10, 16)).hour == 20                       # EDT: 16:00 = 20:00Z
    assert market_close_utc(date(2026, 12, 15)).hour == 21                       # EST
```

### 12.5 `test_contract.py`: one suite, both sources

```python
import asyncio
import random

import pytest

from app.market import PriceCache
from app.market.massive.source import MassiveSource
from app.market.simulator.source import SimulatorSource

from .conftest import FakeMassive, wait_until


@pytest.fixture(params=["simulator", "massive"])
async def source(request):
    cache = PriceCache()
    if request.param == "simulator":
        src = SimulatorSource(cache, interval=0.01, rng=random.Random(42))
    else:
        src = MassiveSource(cache, "test-key", mode="snapshot", poll_interval=0.01,
                            transport=FakeMassive().transport)
    yield src
    await src.stop()


async def test_c1_start_prices_tickers(source):
    await source.start(["AAPL", "MSFT"])
    await wait_until(lambda: "AAPL" in source.cache and "MSFT" in source.cache)


async def test_c2_add_seeds_cache_before_returning(source):
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    assert "PYPL" in source.cache
    assert "PYPL" in source.tracked_tickers()


async def test_c4_remove_stops_writes(source):
    await source.start(["AAPL", "MSFT"])
    await wait_until(lambda: "MSFT" in source.cache)
    await source.remove_ticker("MSFT")
    await asyncio.sleep(0.05)                     # several ticks/polls
    assert "MSFT" not in source.cache
    assert "MSFT" not in source.tracked_tickers()


async def test_c6_stop_is_idempotent(source):
    await source.start(["AAPL"])
    await source.stop()
    await source.stop()
```

C3 and C5 need source-specific setup, so they live in the next two files.

### 12.6 `test_massive_source.py`

```python
import asyncio
import random
from datetime import date

import pytest

from app.market import PriceCache, UnknownTickerError
from app.market.massive.source import MassiveSource
from app.market.simulator.source import SimulatorSource

from .conftest import FakeMassive, wait_until

SUNDAY = date(2026, 10, 18)
DAYS = {
    "2026-10-16": {"AAPL": 191.0, "MSFT": 421.0},
    "2026-10-15": {"AAPL": 189.0, "MSFT": 419.0},
}


def massive(fake: FakeMassive, **kw) -> MassiveSource:
    kw = {"free_tier_spacing": 0, "today": lambda: SUNDAY, **kw}
    return MassiveSource(PriceCache(), "test-key", transport=fake.transport, **kw)


async def test_detects_snapshot_mode():
    fake = FakeMassive()
    src = massive(fake, poll_interval=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    assert src.mode == "snapshot"
    e = src.cache.get("AAPL")
    assert e.price == 190.0 and e.reference_price == 188.1
    await src.stop()


async def test_c3_add_tracked_ticker_makes_no_call():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    before = len(fake.requests)
    await src.add_ticker("AAPL")
    assert len(fake.requests) == before
    await src.stop()


async def test_snapshot_unknown_ticker_rejected():
    src = massive(FakeMassive(), mode="snapshot", poll_interval=10)
    await src.start([])
    with pytest.raises(UnknownTickerError, match="Unknown ticker: QWERTY"):
        await src.add_ticker("QWERTY")
    assert "QWERTY" not in src.tracked_tickers()
    await src.stop()


async def test_c5_poll_errors_keep_prices_and_loop_alive():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    fake.fail_next = 3
    n = len(fake.requests)
    await wait_until(lambda: len(fake.requests) > n + 4)       # kept polling through the 500s
    assert src.cache.get_price("AAPL") == 190.0
    await src.stop()


async def test_free_plan_falls_back_to_eod():
    fake = FakeMassive(snapshot_status=403, days=DAYS)
    src = massive(fake)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    assert src.mode == "eod"
    e = src.cache.get("AAPL")
    assert (e.price, e.reference_price, e.change_percent) == (191.0, 189.0, 1.06)
    assert e.timestamp.isoformat() == "2026-10-16T20:00:00+00:00"
    calls = len(fake.requests)                                 # probe + Fri + Thu = 3
    assert calls == 3
    await src.add_ticker("MSFT")                               # 0 calls
    assert len(fake.requests) == calls
    with pytest.raises(UnknownTickerError):
        await src.add_ticker("ZZZZ")
    await src.stop()


async def test_eod_walk_skips_holiday_and_unpublished_today():
    days = {"2026-10-14": {"AAPL": 180.0}, "2026-10-13": {"AAPL": 178.0}}
    fake = FakeMassive(days=days, forbidden_days={"2026-10-16"})
    src = massive(fake, mode="eod", today=lambda: date(2026, 10, 16))
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    # 16th: 403 (D4), 15th: empty, 14th + 13th: data
    assert [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == [
        "2026-10-16", "2026-10-15", "2026-10-14", "2026-10-13"]
    assert src.cache.get("AAPL").reference_price == 178.0
    await src.stop()


async def test_add_before_ready_times_out_with_503_error():
    fake = FakeMassive(snapshot_status=403, days={})           # never becomes ready
    src = massive(fake, ready_timeout=0.05, error_backoff=10)
    await src.start([])
    from app.market import MarketDataUnavailableError
    with pytest.raises(MarketDataUnavailableError):
        await src.add_ticker("AAPL")
    await src.stop()


async def test_simulator_c5_tick_errors_dont_kill_loop(monkeypatch):
    src = SimulatorSource(PriceCache(), interval=0.01, rng=random.Random(1))
    await src.start(["AAPL"])
    real_step, calls = src.engine.step, {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_step()

    monkeypatch.setattr(src.engine, "step", flaky)
    first = src.cache.get("AAPL")
    await wait_until(lambda: calls["n"] > 3)
    assert src.cache.get("AAPL").timestamp > first.timestamp
    await src.stop()
```

### 12.7 `test_massive_client.py`

```python
import time

import httpx
import pytest

from app.market.massive.client import (
    MassiveAuthError, MassiveClient, MassiveError, PlanNotEntitledError, RateLimitedError,
)


def client_returning(status: int, seen: list | None = None, **kw) -> MassiveClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"tickers": []})
    return MassiveClient("secret-key", transport=httpx.MockTransport(handler), **kw)


@pytest.mark.parametrize("status, exc", [
    (401, MassiveAuthError), (403, PlanNotEntitledError), (429, RateLimitedError), (502, MassiveError),
])
async def test_status_mapping(status, exc):
    with pytest.raises(exc):
        await client_returning(status).snapshots(["AAPL"])


async def test_key_in_header_not_url():
    seen: list[httpx.Request] = []
    await client_returning(200, seen).snapshots(["MSFT", "AAPL"])
    req = seen[0]
    assert req.headers["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in str(req.url)
    assert req.url.params["tickers"] == "AAPL,MSFT"            # sorted, comma-separated


async def test_empty_ticker_list_makes_no_call():
    seen: list[httpx.Request] = []
    assert await client_returning(200, seen).snapshots([]) == {}
    assert seen == []


async def test_min_interval_spaces_calls():
    client = client_returning(200, min_interval=0.05)
    t0 = time.monotonic()
    await client.snapshots(["AAPL"])
    await client.snapshots(["AAPL"])
    assert time.monotonic() - t0 >= 0.04     # slack: Windows' monotonic clock ticks every ~16 ms
```

### 12.8 `test_stream.py` and `test_factory.py`

```python
import json

from app.market import PriceCache, price_events
from app.market.factory import create_market_data_source
from app.market.massive.source import MassiveSource
from app.market.simulator.source import SimulatorSource


class FakeRequest:
    def __init__(self, events: int):
        self.remaining = events

    async def is_disconnected(self) -> bool:
        self.remaining -= 1
        return self.remaining < 0


async def test_event_format():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = [e async for e in price_events(cache, FakeRequest(2), interval=0)]
    assert events[0] == "retry: 2000\n\n"
    assert len(events) == 3                                    # retry + 2 data events
    assert events[1].startswith("data: ") and events[1].endswith("\n\n")
    payload = json.loads(events[1].removeprefix("data: "))
    assert payload["AAPL"]["price"] == 190.0
    assert payload["AAPL"]["timestamp"].endswith("Z")


async def test_empty_cache_sends_empty_object():
    events = [e async for e in price_events(PriceCache(), FakeRequest(1), interval=0)]
    assert events[1] == "data: {}\n\n"


def test_factory_selects_source():
    assert isinstance(create_market_data_source(PriceCache(), {}), SimulatorSource)
    assert isinstance(create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "  "}), SimulatorSource)
    src = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_MODE": "EOD"})
    assert isinstance(src, MassiveSource) and src.mode == "eod"
    bad = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_MODE": "x",
                                                   "MASSIVE_POLL_INTERVAL": "0.1"})
    assert bad.mode is None and bad._poll_interval == 2.0
```

### 12.9 Coverage map

| Requirement | Test |
|---|---|
| GBM math, positivity, events, correlation (PLAN.md §6, §12) | `test_engine.py` |
| Massive parsing (PLAN.md §12) | `test_massive_parse.py` |
| Both sources conform to the interface (PLAN.md §12) | `test_contract.py` + C3/C5 in `test_massive_source.py` |
| Unknown ticker → 400 (PLAN.md §6) | `test_snapshot_unknown_ticker_rejected`, `test_free_plan_falls_back_to_eod` |
| SSE event format (PLAN.md §6) | `test_stream.py` |
| Env-driven source choice (PLAN.md §5) | `test_factory.py` |

---

## 13. Implementation Order & Open Items

### Build order

Each step is independently testable:

1. `errors.py`, `tickers.py`, `models.py`, `cache.py` + `test_core.py`
2. `base.py`
3. Simulator: `seeds.py`, `engine.py` + `test_engine.py`, then `source.py`
4. `stream.py` + `test_stream.py`. **At this point the SSE stream works end to end with the simulator**, and the frontend can develop against it
5. Massive: `parse.py` + tests, `client.py` + tests, `source.py` + tests
6. `factory.py` + `test_factory.py`, `__init__.py`
7. App integration (§9): lifespan, error handlers, watchlist and trade wiring
8. `test_contract.py` across both sources

### PLAN.md updates this design needs

> **✅ Applied** to PLAN.md §5, §6, §8 and §10 on 2026-10-18.

| PLAN.md section | Change |
|---|---|
| §5 Environment Variables | Add optional `MASSIVE_MODE` and `MASSIVE_POLL_INTERVAL` (also in `.env.example`) |
| §6 Massive API | Replace "free tier: poll every 15 seconds" with: free plan → end-of-day prices refreshed every 30 min; snapshots need Starter or above |
| §6 / §8 timestamps | Allow milliseconds: `"2026-01-01T12:00:00.500Z"` |
| §8 Errors | Add **503** "Market data unavailable, try again shortly" (the Massive provider is down or still loading) |
| §10 Technical Notes | Flash on a price change; append chart points only on a new timestamp (§8.3) |
