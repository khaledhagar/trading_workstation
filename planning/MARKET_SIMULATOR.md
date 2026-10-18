# Market Simulator: Approach & Code Structure

The default market data source, used whenever `MASSIVE_API_KEY` is empty. It implements the `MarketDataSource` interface from [`MARKET_INTERFACE.md`](MARKET_INTERFACE.md) and satisfies PLAN.md §6 (Simulator):

- Geometric Brownian motion (GBM) with per-ticker drift and volatility
- A tick every ~500 ms
- Correlated moves (tech moves with tech, everything a bit with the market)
- Occasional 2–5% "events" for drama
- Realistic seed prices; unknown tickers get a random $50–$300 seed and are uncorrelated
- Reference price for change % = the seed price
- In-process, no external dependencies (standard library only)

---

## 1. The Model

### 1.1 GBM step

Each tick, every tracked ticker's price is advanced with the **exact** GBM solution. It's exact rather than an Euler approximation, so prices can never go negative:

```
S(t+Δt) = S(t) · exp( (μ − σ²/2)·Δt + σ·√Δt · Z )
```

| Symbol | Meaning | Units |
|---|---|---|
| `μ` | Annual drift (expected return) | per year, e.g. `0.08` |
| `σ` | Annual volatility | per year, e.g. `0.25` |
| `Δt` | Tick length as a fraction of a **trading year** | `0.5 s / (252 × 6.5 × 3600 s)` ≈ **8.48 × 10⁻⁸** |
| `Z` | Correlated standard normal shock (§1.2) | — |

Time runs at **real-market speed**: one simulated second is one second of trading. Verified numerically:

| Ticker profile | Per-tick move (1σ) | 1-hour move (1σ) |
|---|---|---|
| AAPL, σ 0.25 @ $190 | ≈ $0.014 | ≈ 0.6% |
| TSLA, σ 0.60 @ $250 | ≈ $0.044 | ≈ 1.5% |
| V, σ 0.18 @ $275 | ≈ $0.014 | ≈ 0.4% |

About **73% of ticks change the displayed (cent-rounded) price**, so the watchlist flickers green/red constantly, as PLAN.md's flash animation expects. Over a demo session, drift is negligible (μΔt ≈ 10⁻⁸); it's kept for correctness and for long-running instances.

There is one knob, `time_scale` (default `1.0`), which multiplies `Δt`. `time_scale=60` makes each real second behave like a trading minute: much bigger swings, useful for screenshots or a livelier demo. It's a constructor argument, not an env var.

### 1.2 Correlation: a two-factor model

Instead of building and Cholesky-decomposing an N×N correlation matrix every time a ticker is added, each ticker's shock is a weighted sum of shared factors plus its own noise:

```
Z_i = w_m · M  +  w_s · S_sector(i)  +  w_e · ε_i          with  w_m² + w_s² + w_e² = 1
```

- `M` is one market-wide N(0,1) draw per tick
- `S_k` is one N(0,1) draw per sector per tick
- `ε_i` is one N(0,1) draw per ticker per tick

Because the weights' squares sum to 1, `Z_i` is still standard normal, so `σ` keeps its meaning. The resulting correlations:

| Pair | Correlation | Default |
|---|---|---|
| Same sector | `w_m² + w_s²` | **0.6** |
| Different sectors | `w_m²` | **0.3** |
| Unknown (sector `None`) vs anything | `0` (uses `w_m = w_s = 0`, `w_e = 1`) | **0** |

Defaults: `w_m = √0.3`, `w_s = √0.3`, `w_e = √0.4`. A 200k-draw check gave 0.599 and 0.302. Adding or removing a ticker is O(1), and a tick is O(N) using `random.gauss`. Tens of tickers cost microseconds, so **numpy isn't needed**.

### 1.3 Events

Each tick, each ticker independently has probability `p = interval / event_mean_seconds` of an event (default `event_mean_seconds = 600`, i.e. about one event per ticker every 10 minutes, or **about one per minute across a 10-ticker watchlist**).

An event multiplies the price once, on top of the GBM step:

```
S ← S · (1 + sign · U(0.02, 0.05))      sign = ±1 with equal probability
```

That's a single-tick jump of 2–5%: an obvious flash, and an equally obvious step in the chart. Events are logged at DEBUG level (`"event: TSLA -3.4%"`) so they're easy to spot while developing.

### 1.4 Seeds and reference price

- On `add`, a ticker starts at its seed price. The **seed is written to the cache as both `price` and `reference_price`**, so `change_percent` starts at 0.00% and measures the move since the ticker joined the simulation (PLAN.md §6).
- The reference never changes while the process runs. Restarting the server re-seeds every ticker; the simulator keeps no state in the DB.
- Removing a ticker and adding it again re-seeds it (fresh reference). This only happens when it's neither watched nor held, so nothing visible depends on continuity.

---

## 2. Seed Data

```python
# simulator/seeds.py
from dataclasses import dataclass

@dataclass(frozen=True)
class TickerProfile:
    seed_price: float
    drift: float        # μ, annual
    volatility: float   # σ, annual
    sector: str | None  # None = uncorrelated

DEFAULT_PROFILES: dict[str, TickerProfile] = {
    #                     seed    μ     σ     sector
    "AAPL":  TickerProfile(190.0, 0.08, 0.25, "tech"),
    "GOOGL": TickerProfile(175.0, 0.08, 0.28, "tech"),
    "MSFT":  TickerProfile(420.0, 0.08, 0.24, "tech"),
    "META":  TickerProfile(500.0, 0.10, 0.35, "tech"),
    "NVDA":  TickerProfile(130.0, 0.15, 0.50, "tech"),
    "AMZN":  TickerProfile(185.0, 0.10, 0.30, "consumer"),
    "TSLA":  TickerProfile(250.0, 0.10, 0.60, "consumer"),
    "NFLX":  TickerProfile(650.0, 0.10, 0.40, "consumer"),
    "JPM":   TickerProfile(200.0, 0.06, 0.20, "finance"),
    "V":     TickerProfile(275.0, 0.06, 0.18, "finance"),
}

# Unknown tickers (PLAN.md §6): random seed in [50, 300], default vol, no sector
UNKNOWN_PRICE_RANGE = (50.0, 300.0)
UNKNOWN_DRIFT = 0.05
UNKNOWN_VOLATILITY = 0.30
```

The ten defaults are PLAN.md §7's seed watchlist. Prices are realistic ballparks; nothing depends on their exact values. More well-known symbols (e.g. `AMD`, `INTC`, `BAC`, `DIS`, `PYPL`) can be added to the table and then get a realistic seed and a sector instead of the random fallback.

---

## 3. Code Structure

```
backend/app/market/simulator/
├── __init__.py   # exports SimulatorSource
├── seeds.py      # TickerProfile + DEFAULT_PROFILES (§2)
├── engine.py     # SimulatorEngine: pure math, no asyncio, no cache, no clock
└── source.py     # SimulatorSource(MarketDataSource): asyncio loop around the engine
```

The split matters for testing. **`engine.py` is deterministic given an RNG**: no time, no I/O, no asyncio. All the math tests run on it synchronously. `source.py` is a thin adapter, tested by the shared contract suite in `MARKET_INTERFACE.md` §10.

### 3.1 `engine.py`

```python
import math
import random
from dataclasses import dataclass

from .seeds import (DEFAULT_PROFILES, UNKNOWN_DRIFT, UNKNOWN_PRICE_RANGE,
                    UNKNOWN_VOLATILITY, TickerProfile)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600   # 5,896,800

@dataclass
class _State:
    price: float          # full precision; rounding happens in the cache
    profile: TickerProfile


class SimulatorEngine:
    def __init__(
        self,
        rng: random.Random | None = None,
        tick_seconds: float = 0.5,
        time_scale: float = 1.0,
        market_weight: float = math.sqrt(0.3),
        sector_weight: float = math.sqrt(0.3),
        event_mean_seconds: float = 600.0,
        event_range: tuple[float, float] = (0.02, 0.05),
    ) -> None:
        self.rng = rng or random.Random()
        self.dt = tick_seconds * time_scale / TRADING_SECONDS_PER_YEAR
        self.w_m, self.w_s = market_weight, sector_weight
        self.w_e = math.sqrt(1.0 - market_weight**2 - sector_weight**2)
        self.event_prob = tick_seconds / event_mean_seconds
        self.event_range = event_range
        self._states: dict[str, _State] = {}

    # --- membership -------------------------------------------------------
    def add(self, ticker: str) -> float:
        """Start simulating `ticker`; returns its seed price. Idempotent."""
        if ticker in self._states:
            return self._states[ticker].price
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

    # --- simulation ---------------------------------------------------------
    def step(self) -> dict[str, float]:
        """Advance every ticker by one tick. Returns {ticker: new price}."""
        market = self.rng.gauss(0.0, 1.0)
        sectors: dict[str, float] = {}
        sqrt_dt = math.sqrt(self.dt)
        out: dict[str, float] = {}

        for ticker, st in self._states.items():
            p = st.profile
            if p.sector is None:                       # uncorrelated
                z = self.rng.gauss(0.0, 1.0)
            else:
                if p.sector not in sectors:
                    sectors[p.sector] = self.rng.gauss(0.0, 1.0)
                z = (self.w_m * market
                     + self.w_s * sectors[p.sector]
                     + self.w_e * self.rng.gauss(0.0, 1.0))

            st.price *= math.exp((p.drift - 0.5 * p.volatility**2) * self.dt
                                 + p.volatility * sqrt_dt * z)

            if self.rng.random() < self.event_prob:   # 2–5% shock
                sign = 1.0 if self.rng.random() < 0.5 else -1.0
                st.price *= 1.0 + sign * self.rng.uniform(*self.event_range)

            out[ticker] = st.price
        return out
```

Notes:

- Sector draws are generated lazily inside the loop. Their order depends on dict iteration order, which is deterministic in Python, so a fixed `rng` seed reproduces runs exactly.
- The engine keeps **full-precision** prices. If it stored rounded prices, sub-cent drift would be lost every tick and low-volatility tickers would stall.

### 3.2 `source.py`

```python
import asyncio
import logging
import random
from collections.abc import Iterable

from ..base import MarketDataSource
from ..cache import PriceCache
from .engine import SimulatorEngine

logger = logging.getLogger(__name__)


class SimulatorSource(MarketDataSource):
    def __init__(self, cache: PriceCache, *, interval: float = 0.5,
                 rng: random.Random | None = None, time_scale: float = 1.0) -> None:
        super().__init__(cache)
        self.interval = interval
        self.engine = SimulatorEngine(rng=rng, tick_seconds=interval, time_scale=time_scale)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        for t in tickers:
            self._seed(t)                    # C1: priced immediately, before the first tick
        self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None                # C6: idempotent

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self.engine.tickers():  # C3
            self._seed(ticker)                   # C2: cache seeded before returning
        # The simulator accepts any well-formed ticker, so it never raises UnknownTickerError.

    async def remove_ticker(self, ticker: str) -> None:
        self.engine.remove(ticker)
        self.cache.remove(ticker)                # C4

    def tracked_tickers(self) -> frozenset[str]:
        return self.engine.tickers()

    # --- internals ------------------------------------------------------------
    def _seed(self, ticker: str) -> None:
        seed = self.engine.add(ticker)
        self.cache.update(ticker, seed, reference_price=seed)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                for ticker, price in self.engine.step().items():
                    self.cache.update(ticker, price)       # reference kept from the seed
            except Exception:                              # C5: never let the loop die
                logger.exception("Simulator tick failed")
            next_tick += self.interval
            await asyncio.sleep(max(0.0, next_tick - loop.time()))
```

- **Fixed cadence:** sleeping until `next_tick` (instead of a flat `sleep(0.5)`) keeps the rate at 2 ticks/second regardless of how long a tick takes, so timestamps stay evenly spaced in the charts.
- **No awaits inside a tick**, so `add_ticker`/`remove_ticker` from request handlers can never interleave with a half-finished tick. No locks needed.
- `step()` and the cache writes for 10–50 tickers take well under a millisecond, so the event loop (and with it the SSE streams and the API) is never blocked.

---

## 4. Lifecycle

```
lifespan startup
  └─ create_market_data_source(cache)          → SimulatorSource (no MASSIVE_API_KEY)
  └─ await source.start(watchlist ∪ positions)  → each ticker seeded into the cache
                                                  background task: tick every 500 ms
POST /api/watchlist {"ticker": "PYPL"}
  └─ normalize_ticker → await source.add_ticker("PYPL")
                        → random seed in [50, 300], cache seeded, ticks from now on
DELETE /api/watchlist/PYPL (not held)
  └─ sync_tickers(...) → remove_ticker("PYPL") → gone from engine + cache + SSE
lifespan shutdown
  └─ await source.stop()
```

---

## 5. Testing

All engine tests use `SimulatorEngine(rng=random.Random(42))` and call `step()` directly, so there's no asyncio and no sleeping.

| Test | Assertion |
|---|---|
| Seeds | `add("AAPL")` returns `190.0`; an unknown ticker gets a seed in [50, 300] with σ = 0.30 and sector `None` |
| Idempotent add | Adding twice keeps the same state/price |
| Positivity | 100k steps with events at 10× frequency → all prices > 0 |
| GBM statistics | With events disabled (`event_mean_seconds=inf`) over many steps, the mean and stdev of `log(S_{t+1}/S_t)` match `(μ−σ²/2)Δt` and `σ√Δt` within a tolerance |
| Correlation | With events disabled, log-return correlation ≈ 0.6 (AAPL/MSFT), ≈ 0.3 (AAPL/JPM), ≈ 0 (unknown/AAPL), within ±0.05 |
| Events | With `event_mean_seconds` tiny, the jump sizes observed fall within 2–5% |
| Determinism | Two engines with the same seed and the same add order → identical price paths |
| `time_scale` | Per-tick log-return stdev scales by `√time_scale` |
| Source contract | The parametrized C1–C6 suite from `MARKET_INTERFACE.md` §10, run with `interval=0.01` |
| Reference price | After many ticks, `cache.get("AAPL").reference_price == 190.0`, and `change_percent` matches `(price−190)/190·100` |

---

## 6. Deliberate Non-Features

- **No market hours.** The simulator trades 24/7, so the demo always moves.
- **No mean reversion and no volatility clustering.** GBM plus jumps is enough for a convincing terminal, and stays easy to explain and test.
- **No persistence of simulated prices.** A restart re-seeds. Portfolio history in `portfolio_snapshots` stays meaningful, because positions keep their `avg_cost` and are revalued at the fresh seed prices.
- **No order-book impact.** The user's trades don't move the price (market orders, instant fill, PLAN.md §2).
