from pathlib import Path

import pytest

import db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return db.init_db(tmp_path / "test.db")


@pytest.fixture
def conn(db_path: Path):
    with db.connect(db_path) as c:
        yield c


class Prices:
    """Mutable fake price source: prices["AAPL"] = 190.0; prices.get_price("AAPL")."""

    def __init__(self, **prices: float):
        self.prices: dict[str, float] = dict(prices)

    def __setitem__(self, k, v):
        self.prices[k] = v

    def get_price(self, ticker: str):
        return self.prices.get(ticker)


@pytest.fixture
def prices() -> Prices:
    return Prices(AAPL=190.0, MSFT=400.0, TSLA=250.0)
