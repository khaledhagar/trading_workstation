import json

import pytest
from fastapi.testclient import TestClient

import db
from app.api.stream import SSE_HEADERS, stream_prices
from app.main import create_app
from app.market import MarketDataUnavailableError, PriceCache, UnknownTickerError

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
PRICE_KEYS = {"ticker", "price", "previous_price", "direction", "change_percent", "timestamp"}
PORTFOLIO_KEYS = {"cash_balance", "positions_value", "total_value", "unrealized_pnl", "positions"}
POSITION_KEYS = {"ticker", "quantity", "avg_cost", "current_price", "market_value",
                 "unrealized_pnl", "pnl_percent"}


def tickers(rows):
    return [r["ticker"] for r in rows]


def tracked(client):
    return client.app.state.market.tracked_tickers()


# ------------------------------------------------------------------ system

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_startup_records_a_snapshot(client):
    history = client.get("/api/portfolio/history").json()
    assert len(history) >= 1
    assert history[0]["total_value"] == 10000.0
    assert history[0]["recorded_at"].endswith("Z")


def test_startup_tracks_default_watchlist(client):
    assert tracked(client) == frozenset(DEFAULT_TICKERS)


# ------------------------------------------------------------------ watchlist

def test_get_watchlist_default(client):
    rows = client.get("/api/watchlist").json()
    assert tickers(rows) == DEFAULT_TICKERS
    for row in rows:
        assert set(row) == PRICE_KEYS
        assert row["price"] > 0
        assert row["timestamp"].endswith("Z")


def test_add_and_remove_ticker(client):
    r = client.post("/api/watchlist", json={"ticker": " pypl "})
    assert r.status_code == 200
    rows = r.json()
    assert tickers(rows)[-1] == "PYPL"
    assert rows[-1]["price"] is not None          # seeded immediately
    assert "PYPL" in tracked(client)

    r = client.delete("/api/watchlist/pypl")
    assert r.status_code == 200
    assert "PYPL" not in tickers(r.json())
    assert "PYPL" not in tracked(client)


def test_add_is_idempotent(client):
    first = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert first.status_code == 200
    assert tickers(first.json()).count("AAPL") == 1
    assert tickers(first.json()) == DEFAULT_TICKERS


def test_add_invalid_ticker(client):
    r = client.post("/api/watchlist", json={"ticker": "123"})
    assert r.status_code == 400 and r.json() == {"detail": "Invalid ticker"}


def test_add_missing_field_is_422(client):
    assert client.post("/api/watchlist", json={}).status_code == 422


def test_add_unknown_ticker_400(client, monkeypatch):
    async def reject(ticker):
        raise UnknownTickerError(ticker)
    monkeypatch.setattr(client.app.state.market, "add_ticker", reject)
    r = client.post("/api/watchlist", json={"ticker": "ZZZZ"})
    assert r.status_code == 400 and r.json() == {"detail": "Unknown ticker: ZZZZ"}
    assert "ZZZZ" not in tickers(client.get("/api/watchlist").json())   # never persisted


def test_market_unavailable_is_503(client, monkeypatch):
    async def down(ticker):
        raise MarketDataUnavailableError("provider said: secret internals")
    monkeypatch.setattr(client.app.state.market, "add_ticker", down)
    r = client.post("/api/watchlist", json={"ticker": "ZZZZ"})
    assert r.status_code == 503
    assert r.json() == {"detail": "Market data unavailable, try again shortly"}


def test_delete_not_watched_is_404(client):
    r = client.delete("/api/watchlist/ZZZZ")
    assert r.status_code == 404
    assert "ZZZZ" in r.json()["detail"]


def test_delete_invalid_ticker_is_400(client):
    assert client.delete("/api/watchlist/1AB").status_code == 400


def test_delete_held_ticker_keeps_it_tracked(client):
    assert client.post("/api/portfolio/trade",
                       json={"ticker": "TSLA", "quantity": 2, "side": "buy"}).status_code == 200
    r = client.delete("/api/watchlist/TSLA")
    assert r.status_code == 200 and "TSLA" not in tickers(r.json())
    assert "TSLA" in tracked(client)
    positions = client.get("/api/portfolio").json()["positions"]
    assert positions[0]["ticker"] == "TSLA"

    # selling to zero now drops it from tracking
    r = client.post("/api/portfolio/trade", json={"ticker": "TSLA", "quantity": 2, "side": "sell"})
    assert r.status_code == 200
    assert r.json()["portfolio"]["positions"] == []
    assert "TSLA" not in tracked(client)


def test_empty_watchlist_returns_empty_list(client):
    for t in DEFAULT_TICKERS:
        assert client.delete(f"/api/watchlist/{t}").status_code == 200
    assert client.get("/api/watchlist").json() == []
    assert tracked(client) == frozenset()


# ------------------------------------------------------------------ portfolio & trades

def test_initial_portfolio(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    assert r.json() == {"cash_balance": 10000.0, "positions_value": 0.0, "total_value": 10000.0,
                        "unrealized_pnl": 0.0, "positions": []}


def test_buy_shape_and_cash(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "aapl", "quantity": 10, "side": "buy"})
    assert r.status_code == 200
    body = r.json()
    trade = body["trade"]
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert trade["ticker"] == "AAPL" and trade["side"] == "buy" and trade["quantity"] == 10
    assert trade["executed_at"].endswith("Z")

    portfolio = body["portfolio"]
    assert set(portfolio) == PORTFOLIO_KEYS
    assert portfolio["cash_balance"] == round(10000 - 10 * trade["price"], 2)
    [pos] = portfolio["positions"]
    assert set(pos) == POSITION_KEYS
    assert pos["ticker"] == "AAPL" and pos["quantity"] == 10
    assert pos["avg_cost"] == trade["price"]
    assert client.get("/api/portfolio").json()["cash_balance"] == portfolio["cash_balance"]
    assert len(client.get("/api/portfolio/history").json()) >= 2    # trade snapshot


def test_portfolio_totals_consistent(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 4, "side": "buy"})
    p = client.get("/api/portfolio").json()
    assert p["total_value"] == pytest.approx(p["cash_balance"] + p["positions_value"], abs=0.011)
    assert p["positions_value"] == p["positions"][0]["market_value"]


def test_buy_unwatched_ticker_auto_adds(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "PYPL", "quantity": 1, "side": "buy"})
    assert r.status_code == 200
    assert "PYPL" in tickers(client.get("/api/watchlist").json())
    assert "PYPL" in tracked(client)


def test_insufficient_cash(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "NFLX", "quantity": 1000, "side": "buy"})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Insufficient cash: need $")
    assert r.json()["detail"].endswith("have $10,000.00")
    assert client.get("/api/portfolio").json()["cash_balance"] == 10000.0


def test_insufficient_shares(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 5, "side": "sell"})
    assert r.status_code == 400
    assert r.json() == {"detail": "Insufficient shares: have 0, tried to sell 5"}


def test_sell_unwatched_unheld_does_not_add(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "PYPL", "quantity": 1, "side": "sell"})
    assert r.status_code == 400
    assert "PYPL" not in tickers(client.get("/api/watchlist").json())


def test_partial_sell_keeps_avg_cost(client):
    buy = client.post("/api/portfolio/trade",
                      json={"ticker": "AAPL", "quantity": 3.5, "side": "buy"}).json()
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1.25, "side": "sell"})
    assert r.status_code == 200
    [pos] = r.json()["portfolio"]["positions"]
    assert pos["quantity"] == 2.25
    assert pos["avg_cost"] == buy["trade"]["price"]
    assert "AAPL" in tracked(client)      # still watched


def test_no_price_trade_400(client, monkeypatch):
    async def no_seed(ticker):
        return None
    monkeypatch.setattr(client.app.state.market, "add_ticker", no_seed)
    r = client.post("/api/portfolio/trade", json={"ticker": "ZZZZ", "quantity": 1, "side": "buy"})
    assert r.status_code == 400 and r.json() == {"detail": "No price available for ZZZZ yet"}


@pytest.mark.parametrize("body", [
    {"ticker": "AAPL", "quantity": 0, "side": "buy"},
    {"ticker": "AAPL", "quantity": -1, "side": "buy"},
    {"ticker": "AAPL", "quantity": 1.00001, "side": "buy"},
    {"ticker": "AAPL", "quantity": 1, "side": "hold"},
    {"ticker": "AAPL", "quantity": "lots", "side": "buy"},
    {"ticker": "AAPL", "side": "buy"},
    {"quantity": 1, "side": "buy"},
])
def test_trade_validation_422(client, body):
    assert client.post("/api/portfolio/trade", json=body).status_code == 422


def test_four_decimals_allowed(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 0.1234, "side": "buy"})
    assert r.status_code == 200 and r.json()["trade"]["quantity"] == 0.1234


def test_invalid_ticker_trade_400(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "A1", "quantity": 1, "side": "buy"})
    assert r.status_code == 400 and r.json() == {"detail": "Invalid ticker"}


def test_history_limit(client):
    with db.connect() as conn:
        for i in range(1005):
            db.insert_snapshot(conn, 10000 + i)
    history = client.get("/api/portfolio/history").json()
    assert len(history) == 1000
    assert history[-1]["total_value"] == 11004


# ------------------------------------------------------------------ SSE

class _OneShotRequest:
    def __init__(self, app, events=1):
        self.app = app
        self._left = events

    async def is_disconnected(self):
        self._left -= 1
        return self._left < 0


async def test_sse_route_headers_and_first_event(client):
    response = await stream_prices(_OneShotRequest(client.app))
    assert response.media_type == "text/event-stream"
    for key, value in SSE_HEADERS.items():
        assert response.headers[key] == value
    chunks = [c async for c in response.body_iterator]
    assert chunks[0] == "retry: 2000\n\n"
    assert chunks[1].startswith("data: ") and chunks[1].endswith("\n\n")
    payload = json.loads(chunks[1].removeprefix("data: "))
    assert set(payload) == set(DEFAULT_TICKERS)
    assert set(payload["AAPL"]) == PRICE_KEYS
    assert payload["AAPL"]["direction"] in ("up", "down", "flat")


def test_sse_route_registered(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/stream/prices", "/api/portfolio", "/api/portfolio/trade",
                 "/api/portfolio/history", "/api/watchlist", "/api/watchlist/{ticker}",
                 "/api/health"):
        assert path in paths


# ------------------------------------------------------------------ static mount

def test_static_mount_skipped_when_missing(client):
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_static_mount_serves_index(app_env, monkeypatch):
    static = app_env / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>hello</html>", encoding="utf-8")
    monkeypatch.setenv("STATIC_DIR", str(static))
    with TestClient(create_app(load_env=False)) as c:
        r = c.get("/")
        assert r.status_code == 200 and "hello" in r.text
        assert c.get("/api/health").json() == {"status": "ok"}     # API wins over the mount


def test_llm_warning_when_unconfigured(app_env, monkeypatch, caplog):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with caplog.at_level("WARNING"):
        with TestClient(create_app(load_env=False)):
            pass
    assert any("OPENROUTER_API_KEY" in rec.getMessage() for rec in caplog.records)


def test_persistence_across_restart(app_env):
    with TestClient(create_app(load_env=False)) as c:
        c.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
        c.delete("/api/watchlist/NFLX")
    with TestClient(create_app(load_env=False)) as c:
        assert c.get("/api/portfolio").json()["positions"][0]["ticker"] == "AAPL"
        assert "NFLX" not in tickers(c.get("/api/watchlist").json())
