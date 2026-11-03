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
    """GBM with a two-factor (market + sector) correlation model and random events. Pure math."""

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
        self.event_prob = tick_seconds / event_mean_seconds
        self.event_range = event_range
        self._states: dict[str, _State] = {}

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
