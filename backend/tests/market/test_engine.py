"""Simulator math: synchronous, seeded RNG, no asyncio."""

import math
import random
import statistics

import pytest

from app.market.simulator.engine import TRADING_SECONDS_PER_YEAR, SimulatorEngine
from app.market.simulator.seeds import DEFAULT_PROFILES

NO_EVENTS = math.inf
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def log_returns(engine: SimulatorEngine, tickers: list[str], steps: int) -> dict[str, list[float]]:
    prev = {t: engine.add(t) for t in tickers}
    series: dict[str, list[float]] = {t: [] for t in tickers}
    for _ in range(steps):
        prices = engine.step()
        for t in tickers:
            series[t].append(math.log(prices[t] / prev[t]))
            prev[t] = prices[t]
    return series


class FixedRng(random.Random):
    """gauss() always returns `z`; random() returns 0.99 (no events)."""

    def __init__(self, z: float):
        super().__init__(0)
        self.z = z

    def gauss(self, mu=0.0, sigma=1.0):  # noqa: ARG002
        return self.z

    def random(self):
        return 0.99


# --- seeds & membership --------------------------------------------------------
def test_default_watchlist_has_profiles():
    for t in DEFAULT_WATCHLIST:
        assert t in DEFAULT_PROFILES


def test_seeds():
    e = SimulatorEngine(random.Random(1))
    assert e.add("AAPL") == 190.0
    seed = e.add("ZZZ")
    assert 50.0 <= seed <= 300.0 and seed == round(seed, 2)
    profile = e.profile("ZZZ")
    assert profile.sector is None and profile.volatility == 0.30 and profile.drift == 0.05
    assert e.add("ZZZ") == seed                       # idempotent


def test_add_is_idempotent_after_steps():
    e = SimulatorEngine(random.Random(1))
    e.add("AAPL")
    price = e.step()["AAPL"]
    assert e.add("AAPL") == price                     # no reseed


def test_remove_and_tickers():
    e = SimulatorEngine(random.Random(1))
    e.add("AAPL")
    e.add("MSFT")
    e.remove("AAPL")
    e.remove("NOPE")
    assert e.tickers() == frozenset({"MSFT"})
    assert e.profile("AAPL") is None
    assert set(e.step()) == {"MSFT"}


def test_step_with_no_tickers():
    assert SimulatorEngine(random.Random(1)).step() == {}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tick_seconds": 0},
        {"time_scale": -1},
        {"market_weight": 0.9, "sector_weight": 0.9},
        {"market_weight": -0.1},
        {"event_mean_seconds": 0},
        {"event_range": (0.05, 0.02)},
        {"event_range": (0.5, 1.0)},
    ],
)
def test_rejects_bad_config(kwargs):
    with pytest.raises(ValueError):
        SimulatorEngine(random.Random(1), **kwargs)


def test_dt_is_real_market_speed():
    e = SimulatorEngine()
    assert e.dt == pytest.approx(0.5 / TRADING_SECONDS_PER_YEAR)
    assert e.dt == pytest.approx(8.48e-8, rel=1e-3)
    assert e.w_m**2 + e.w_s**2 + e.w_e**2 == pytest.approx(1.0)


# --- GBM math --------------------------------------------------------------------
@pytest.mark.parametrize("z", [0.0, 1.0, -2.5])
def test_single_step_matches_exact_gbm_formula(z):
    e = SimulatorEngine(FixedRng(z))
    e.add("AAPL")
    p = DEFAULT_PROFILES["AAPL"]
    # With every draw equal to z, Z_i = (w_m + w_s + w_e)·z
    z_i = (e.w_m + e.w_s + e.w_e) * z
    expected = 190.0 * math.exp((p.drift - 0.5 * p.volatility**2) * e.dt + p.volatility * math.sqrt(e.dt) * z_i)
    assert e.step()["AAPL"] == pytest.approx(expected, rel=1e-12)


def test_unknown_ticker_uses_only_its_own_noise():
    e = SimulatorEngine(FixedRng(1.0))
    seed = e.add("ZZZ")
    expected = seed * math.exp((0.05 - 0.5 * 0.30**2) * e.dt + 0.30 * math.sqrt(e.dt) * 1.0)
    assert e.step()["ZZZ"] == pytest.approx(expected, rel=1e-12)


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


def test_mean_log_return_matches_drift_with_large_time_scale():
    # Drift is invisible at real speed; scale time up so (μ − σ²/2)Δt dominates the noise.
    e = SimulatorEngine(random.Random(9), event_mean_seconds=NO_EVENTS, time_scale=1e6)
    r = log_returns(e, ["AAPL"], 40_000)["AAPL"]
    p = DEFAULT_PROFILES["AAPL"]
    expected_mean = (p.drift - 0.5 * p.volatility**2) * e.dt
    standard_error = p.volatility * math.sqrt(e.dt) / math.sqrt(len(r))
    assert abs(statistics.fmean(r) - expected_mean) < 4 * standard_error


def test_correlations():
    e = SimulatorEngine(random.Random(4), event_mean_seconds=NO_EVENTS)
    r = log_returns(e, ["AAPL", "MSFT", "JPM", "ZZZ"], 20_000)
    assert abs(statistics.correlation(r["AAPL"], r["MSFT"]) - 0.6) < 0.05   # same sector
    assert abs(statistics.correlation(r["AAPL"], r["JPM"]) - 0.3) < 0.05    # cross sector
    assert abs(statistics.correlation(r["AAPL"], r["ZZZ"])) < 0.05          # unknown


def test_shocks_are_standard_normal():
    e = SimulatorEngine(random.Random(8), event_mean_seconds=NO_EVENTS)
    r = log_returns(e, ["MSFT"], 20_000)["MSFT"]
    p = DEFAULT_PROFILES["MSFT"]
    z = [(x - (p.drift - 0.5 * p.volatility**2) * e.dt) / (p.volatility * math.sqrt(e.dt)) for x in r]
    assert abs(statistics.fmean(z)) < 0.05
    assert abs(statistics.stdev(z) - 1) < 0.03


# --- events --------------------------------------------------------------------
def test_event_size():
    e = SimulatorEngine(random.Random(5), event_mean_seconds=0.5)          # event every tick
    prev = e.add("AAPL")
    ups = downs = 0
    for _ in range(500):
        price = e.step()["AAPL"]
        move = price / prev - 1
        assert 0.0195 <= abs(move) <= 0.0505
        ups += move > 0
        downs += move < 0
        prev = price
    assert ups > 150 and downs > 150                                      # both signs occur


def test_event_rate():
    e = SimulatorEngine(random.Random(6), event_mean_seconds=50.0)        # p = 0.01 per tick
    prev = e.add("AAPL")
    jumps, steps = 0, 20_000
    for _ in range(steps):
        price = e.step()["AAPL"]
        jumps += abs(price / prev - 1) > 0.015
        prev = price
    assert 140 <= jumps <= 260                                             # expected 200


def test_events_disabled():
    e = SimulatorEngine(random.Random(7), event_mean_seconds=NO_EVENTS)
    assert e.event_prob == 0.0
    prev = e.add("TSLA")
    for _ in range(5_000):
        price = e.step()["TSLA"]
        assert abs(price / prev - 1) < 0.01
        prev = price


# --- determinism & time scale ----------------------------------------------------
def test_deterministic():
    paths = []
    for _ in range(2):
        e = SimulatorEngine(random.Random(42))
        e.add("AAPL")
        e.add("ZZZ")
        paths.append([e.step() for _ in range(100)])
    assert paths[0] == paths[1]


def test_time_scale():
    base = SimulatorEngine(random.Random(6), event_mean_seconds=NO_EVENTS)
    fast = SimulatorEngine(random.Random(6), event_mean_seconds=NO_EVENTS, time_scale=60)
    s1 = statistics.stdev(log_returns(base, ["AAPL"], 10_000)["AAPL"])
    s2 = statistics.stdev(log_returns(fast, ["AAPL"], 10_000)["AAPL"])
    assert abs(s2 / s1 / math.sqrt(60) - 1) < 0.05


def test_most_ticks_change_the_displayed_price():
    # MARKET_SIMULATOR.md §1.1: roughly 3 in 4 ticks move AAPL by at least a cent,
    # so the watchlist flashes constantly.
    e = SimulatorEngine(random.Random(11), event_mean_seconds=NO_EVENTS)
    prev = round(e.add("AAPL"), 2)
    changed = 0
    for _ in range(5_000):
        cents = round(e.step()["AAPL"], 2)
        changed += cents != prev
        prev = cents
    assert 0.6 < changed / 5_000 < 0.85
