"""Service-layer tests with a frozen price cache (simulator started but never ticking)."""

from types import SimpleNamespace

import pytest

import db
from app.market import (
    InvalidTickerError,
    PriceCache,
    UnknownTickerError,
    create_market_data_source,
)
from app.services import (
    NotInWatchlistError,
    add_ticker,
    build_portfolio,
    remove_ticker,
    resync_market,
    trade,
    watchlist_rows,
)
from app.services.portfolio import record_snapshot


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "svc.db"))
    db.init_db()
    cache = PriceCache()
    market = create_market_data_source(cache, env={})    # simulator, never started → no ticks
    return SimpleNamespace(price_cache=cache, market=market)


async def _seed(state, ticker, price):
    await state.market.add_ticker(ticker)
    state.price_cache.update(ticker, price, reference_price=price)


def test_build_portfolio_empty(state):
    with db.connect() as conn:
        assert build_portfolio(conn, state.price_cache) == {
            "cash_balance": 10000.0, "positions_value": 0.0, "total_value": 10000.0,
            "unrealized_pnl": 0.0, "positions": [],
        }


async def test_trade_and_portfolio_math(state):
    await _seed(state, "AAPL", 100.0)
    result = await trade(state, "aapl", "buy", 4)
    assert result["trade"]["price"] == 100.0
    assert result["portfolio"]["cash_balance"] == 9600.0

    state.price_cache.update("AAPL", 110.0)
    with db.connect() as conn:
        p = build_portfolio(conn, state.price_cache)
    assert p["positions"] == [{
        "ticker": "AAPL", "quantity": 4, "avg_cost": 100.0, "current_price": 110.0,
        "market_value": 440.0, "unrealized_pnl": 40.0, "pnl_percent": 10.0,
    }]
    assert p["positions_value"] == 440.0
    assert p["total_value"] == 10040.0
    assert p["unrealized_pnl"] == 40.0


async def test_weighted_avg_cost_and_loss(state):
    await _seed(state, "AAPL", 100.0)
    await trade(state, "AAPL", "buy", 1)
    state.price_cache.update("AAPL", 200.0)
    await trade(state, "AAPL", "buy", 1)
    state.price_cache.update("AAPL", 120.0)
    with db.connect() as conn:
        [pos] = build_portfolio(conn, state.price_cache)["positions"]
    assert pos["avg_cost"] == 150.0
    assert pos["unrealized_pnl"] == -60.0
    assert pos["pnl_percent"] == -20.0


async def test_missing_cache_price_values_at_avg_cost(state):
    await _seed(state, "AAPL", 100.0)
    await trade(state, "AAPL", "buy", 2)
    state.price_cache.remove("AAPL")
    with db.connect() as conn:
        p = build_portfolio(conn, state.price_cache)
    assert p["positions"][0]["current_price"] == 100.0
    assert p["total_value"] == 10000.0


async def test_buy_auto_adds_to_watchlist(state):
    result = await trade(state, "pypl", "buy", 1)
    assert result["trade"]["ticker"] == "PYPL"
    with db.connect() as conn:
        assert "PYPL" in db.list_watchlist(conn)
    assert "PYPL" in state.market.tracked_tickers()


async def test_sell_to_zero_untracks_unwatched(state):
    await trade(state, "PYPL", "buy", 1)
    await remove_ticker(state, "PYPL")
    assert "PYPL" in state.market.tracked_tickers()       # still held
    await trade(state, "PYPL", "sell", 1)
    assert "PYPL" not in state.market.tracked_tickers()
    assert "PYPL" not in state.price_cache


async def test_sell_to_zero_keeps_watched(state):
    await _seed(state, "AAPL", 100.0)
    await add_ticker(state, "AAPL")
    await trade(state, "AAPL", "buy", 1)
    await trade(state, "AAPL", "sell", 1)
    assert "AAPL" in state.market.tracked_tickers()


async def test_trade_errors(state):
    await _seed(state, "AAPL", 100.0)
    with pytest.raises(db.TradeError, match=r"^Insufficient cash: need \$100,000.00, have \$10,000.00$"):
        await trade(state, "AAPL", "buy", 1000)
    with pytest.raises(db.TradeError, match=r"^Insufficient shares: have 0, tried to sell 1.5$"):
        await trade(state, "AAPL", "sell", 1.5)
    with pytest.raises(InvalidTickerError):
        await trade(state, "1BAD", "buy", 1)


async def test_add_ticker_idempotent_and_rows(state):
    rows = await add_ticker(state, " pypl ")
    again = await add_ticker(state, "PYPL")
    assert [r["ticker"] for r in rows] == [r["ticker"] for r in again]
    assert [r["ticker"] for r in again].count("PYPL") == 1
    assert again[-1]["price"] is not None


async def test_add_unknown_ticker_not_persisted(state, monkeypatch):
    async def reject(ticker):
        raise UnknownTickerError(ticker)
    monkeypatch.setattr(state.market, "add_ticker", reject)
    with pytest.raises(UnknownTickerError):
        await add_ticker(state, "ZZZZ")
    with db.connect() as conn:
        assert "ZZZZ" not in db.list_watchlist(conn)


async def test_remove_not_watched(state):
    with pytest.raises(NotInWatchlistError, match="ZZZZ"):
        await remove_ticker(state, "zzzz")


def test_watchlist_rows_null_without_price(state):
    with db.connect() as conn:
        rows = watchlist_rows(conn, state.price_cache)
    assert rows[0] == {"ticker": "AAPL", "price": None, "previous_price": None,
                       "direction": None, "change_percent": None, "timestamp": None}


async def test_resync_market_matches_db(state):
    await resync_market(state)
    with db.connect() as conn:
        assert state.market.tracked_tickers() == frozenset(db.tracked_tickers(conn))


async def test_record_snapshot(state):
    await _seed(state, "AAPL", 100.0)
    await trade(state, "AAPL", "buy", 10)
    state.price_cache.update("AAPL", 101.0)
    assert record_snapshot(state.price_cache) == 10010.0
    with db.connect() as conn:
        assert db.list_snapshots(conn)[-1]["total_value"] == 10010.0
