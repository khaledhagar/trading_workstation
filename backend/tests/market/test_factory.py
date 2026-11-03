import pytest

from app.market import PriceCache, create_market_data_source
from app.market.massive.source import MassiveSource
from app.market.simulator.source import SimulatorSource


@pytest.mark.parametrize("env", [{}, {"MASSIVE_API_KEY": ""}, {"MASSIVE_API_KEY": "  "}])
def test_no_key_selects_simulator(env):
    assert isinstance(create_market_data_source(PriceCache(), env), SimulatorSource)


def test_massive_ignored_settings_without_key():
    src = create_market_data_source(PriceCache(), {"MASSIVE_MODE": "eod", "MASSIVE_POLL_INTERVAL": "5"})
    assert isinstance(src, SimulatorSource)


def test_key_selects_massive_with_defaults():
    cache = PriceCache()
    src = create_market_data_source(cache, {"MASSIVE_API_KEY": " k "})
    assert isinstance(src, MassiveSource)
    assert src.cache is cache and src.mode is None and src._poll_interval == 15.0
    assert src._api_key == "k"


@pytest.mark.parametrize("raw, mode", [("EOD", "eod"), (" snapshot ", "snapshot"), ("", None), ("x", None)])
def test_mode(raw, mode):
    src = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_MODE": raw})
    assert src.mode == mode


@pytest.mark.parametrize(
    "raw, interval",
    [("5", 5.0), ("2.5", 2.5), ("0.1", 2.0), ("-3", 2.0), ("abc", 15.0), ("", 15.0), ("nan", 15.0), ("inf", 15.0)],
)
def test_poll_interval(raw, interval):
    src = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": raw})
    assert src._poll_interval == interval


def test_defaults_to_process_environment(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "from-env")
    assert isinstance(create_market_data_source(PriceCache()), MassiveSource)
    monkeypatch.delenv("MASSIVE_API_KEY")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorSource)
