from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerProfile:
    seed_price: float
    drift: float          # μ, annual
    volatility: float     # σ, annual
    sector: str | None    # None = uncorrelated with everything


# The first ten are PLAN.md §7's default watchlist; the rest are common additions
# that deserve a realistic seed and a sector instead of the random fallback.
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
