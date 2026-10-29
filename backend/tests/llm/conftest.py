"""Fixtures for the chat tests: temp SQLite DB, fake market source, no network."""

from types import SimpleNamespace

import pytest

import db
from app.market import PriceCache, UnknownTickerError

PRICES = {"AAPL": 190.0, "MSFT": 420.0, "PYPL": 70.0, "TSLA": 250.0, "GOOGL": 175.0, "AMZN": 180.0,
          "NVDA": 120.0, "META": 500.0, "JPM": 200.0, "V": 280.0, "NFLX": 650.0, "BRK.B": 450.0}


class FakeMarket:
    """Duck-typed MarketDataSource: knows PRICES, seeds the cache on add."""

    def __init__(self, cache: PriceCache):
        self.cache = cache
        self.tracked: set[str] = set()

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self.tracked:
            return
        if ticker not in PRICES:
            raise UnknownTickerError(ticker)
        self.cache.update(ticker, PRICES[ticker])
        self.tracked.add(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self.tracked.discard(ticker)

    async def sync_tickers(self, desired) -> None:
        desired = set(desired)
        for t in desired - self.tracked:
            await self.add_ticker(t)
        for t in self.tracked - desired:
            await self.remove_ticker(t)

    def tracked_tickers(self) -> frozenset[str]:
        return frozenset(self.tracked)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    db.init_db(path)
    return path


@pytest.fixture
async def state(temp_db):
    cache = PriceCache()
    market = FakeMarket(cache)
    with db.connect() as conn:
        await market.sync_tickers(db.tracked_tickers(conn))
    return SimpleNamespace(price_cache=cache, market=market)


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@pytest.fixture
def real_llm(monkeypatch):
    """Real-client path with a fake key; tests must monkeypatch litellm.acompletion."""
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
