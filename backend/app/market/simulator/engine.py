"""Pure simulation math: no asyncio, no clock, no cache. Deterministic given an RNG.

    S(t+Δt) = S(t) · exp((μ − σ²/2)·Δt + σ·√Δt·Z)      exact GBM step, never negative
    Z_i     = w_m·M + w_s·S_sector(i) + w_e·ε_i         w_m² + w_s² + w_e² = 1
    event:  S ← S · (1 ± U(0.02, 0.05))  with p = tick_seconds / event_mean_seconds

Defaults give a correlation of 0.6 within a sector, 0.3 across sectors and 0 for
tickers without a sector (MARKET_SIMULATOR.md §1).
"""

import logging
import math
import random
from dataclasses import dataclass

from ..cache import MIN_PRICE
from .seeds import (
    DEFAULT_PROFILES,
    UNKNOWN_DRIFT,
    UNKNOWN_PRICE_RANGE,
    UNKNOWN_VOLATILITY,
    TickerProfile,
)

logger = logging.getLogger(__name__)

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
        if market_weight < 0 or sector_weight < 0 or market_weight**2 + sector_weight**2 > 1 + 1e-12:
            raise ValueError("weights must be ≥ 0 with market_weight² + sector_weight² ≤ 1")
        if event_mean_seconds <= 0:
            raise ValueError("event_mean_seconds must be > 0 (use math.inf to disable events)")
        low, high = event_range
        if not 0 <= low <= high < 1:
            raise ValueError("event_range must satisfy 0 ≤ low ≤ high < 1")

        self.rng = rng or random.Random()
        self.dt = tick_seconds * time_scale / TRADING_SECONDS_PER_YEAR
        self._sqrt_dt = math.sqrt(self.dt)
        self.w_m = market_weight
        self.w_s = sector_weight
        self.w_e = math.sqrt(max(0.0, 1.0 - market_weight**2 - sector_weight**2))
        self.event_prob = min(1.0, tick_seconds / event_mean_seconds)   # inf → 0.0 (events off)
        self.event_range = event_range
        self._states: dict[str, _State] = {}

    # --- membership ----------------------------------------------------------
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

    # --- simulation ----------------------------------------------------------
    def step(self) -> dict[str, float]:
        """Advance every ticker by one tick. Returns {ticker: new full-precision price}.

        Draw order follows dict order, which is deterministic, so a fixed RNG seed
        reproduces a run exactly."""
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
                move = sign * self.rng.uniform(*self.event_range)
                st.price *= 1.0 + move
                logger.debug("event: %s %+.1f%%", ticker, move * 100)

            # GBM never reaches 0, but a long run could drift below a cent, which the
            # cache rejects. Floor it so a tick can't fail. Unreachable from realistic seeds.
            if st.price < MIN_PRICE:
                st.price = MIN_PRICE

            out[ticker] = st.price
        return out
