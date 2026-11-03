import json

import pytest

from app.chat import LLMResponse, mock_completion, summarize_actions


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_fresh_start(client):
    wl = client.get("/api/watchlist").json()
    assert [w["ticker"] for w in wl] == ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
                                         "NVDA", "META", "JPM", "V", "NFLX"]
    assert all(w["price"] > 0 and w["timestamp"].endswith("Z") for w in wl)
    p = client.get("/api/portfolio").json()
    assert p == {"cash_balance": 10000.0, "positions_value": 0.0, "total_value": 10000.0,
                 "unrealized_pnl": 0.0, "positions": []}
    hist = client.get("/api/portfolio/history").json()
    assert len(hist) >= 1 and hist[0]["total_value"] == 10000.0


def test_watchlist_add_remove(client):
    r = client.post("/api/watchlist", json={"ticker": " pypl "})
    assert r.status_code == 200 and r.json()[-1]["ticker"] == "PYPL"
    assert client.post("/api/watchlist", json={"ticker": "PYPL"}).status_code == 200  # idempotent
    assert sum(w["ticker"] == "PYPL" for w in client.get("/api/watchlist").json()) == 1
    assert client.post("/api/watchlist", json={"ticker": "12AB"}).json() == {"detail": "Invalid ticker"}
    r = client.delete("/api/watchlist/pypl")
    assert r.status_code == 200 and "PYPL" not in [w["ticker"] for w in r.json()]
    r = client.delete("/api/watchlist/IBM")
    assert r.status_code == 404 and r.json()["detail"] == "IBM is not in the watchlist"


def test_buy_and_sell_flow(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "buy"})
    assert r.status_code == 200, r.text
    body = r.json()
    price = body["trade"]["price"]
    port = body["portfolio"]
    assert port["cash_balance"] == round(10000 - 10 * price, 2)
    assert port["positions"][0]["ticker"] == "AAPL" and port["positions"][0]["quantity"] == 10

    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 4, "side": "sell"})
    assert r.json()["portfolio"]["positions"][0]["quantity"] == 6
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 6, "side": "sell"})
    assert r.json()["portfolio"]["positions"] == []
    assert len(client.get("/api/portfolio/history").json()) >= 4  # startup + 3 trades


def test_weighted_average_cost(client, monkeypatch):
    app = client.app
    cache = app.state.price_cache
    # Freeze the simulator so fills are at known prices.
    import asyncio
    client.portal.call(app.state.market.stop)
    cache.update("MSFT", 100.0)
    client.post("/api/portfolio/trade", json={"ticker": "MSFT", "quantity": 1, "side": "buy"})
    cache.update("MSFT", 200.0)
    client.post("/api/portfolio/trade", json={"ticker": "MSFT", "quantity": 3, "side": "buy"})
    pos = client.get("/api/portfolio").json()["positions"][0]
    assert pos["avg_cost"] == 175.0
    assert pos["unrealized_pnl"] == 100.0 and pos["pnl_percent"] == pytest.approx(14.29)
    cache.update("MSFT", 150.0)  # selling at a loss
    r = client.post("/api/portfolio/trade", json={"ticker": "MSFT", "quantity": 2, "side": "sell"})
    pos = r.json()["portfolio"]["positions"][0]
    assert pos["avg_cost"] == 175.0 and pos["quantity"] == 2
    assert r.json()["portfolio"]["cash_balance"] == 10000 - 100 - 600 + 300


def test_trade_errors(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "NFLX", "quantity": 1000, "side": "buy"})
    assert r.status_code == 400 and r.json()["detail"].startswith("Insufficient cash: need $")
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "sell"})
    assert r.status_code == 400 and r.json()["detail"] == "Insufficient shares: have 0, tried to sell 1"
    for bad in ({"ticker": "AAPL", "quantity": 0, "side": "buy"},
                {"ticker": "AAPL", "quantity": 1.00001, "side": "buy"},
                {"ticker": "AAPL", "side": "buy"},
                {"ticker": "AAPL", "quantity": 1, "side": "short"}):
        assert client.post("/api/portfolio/trade", json=bad).status_code == 422
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 0.1234, "side": "buy"})
    assert r.status_code == 200


def test_buy_unwatched_autoadds_and_sell_untracks(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "PYPL", "quantity": 1, "side": "buy"})
    assert r.status_code == 200
    assert "PYPL" in [w["ticker"] for w in client.get("/api/watchlist").json()]
    # Removing a held ticker keeps it priced.
    client.delete("/api/watchlist/PYPL")
    assert "PYPL" in client.app.state.price_cache
    client.post("/api/portfolio/trade", json={"ticker": "PYPL", "quantity": 1, "side": "sell"})
    assert "PYPL" not in client.app.state.price_cache


def test_sse_stream(client):
    with client.stream("GET", "/api/stream/prices") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = r.iter_lines()
        assert next(lines) == "retry: 2000"
        data = next(l for l in lines if l.startswith("data:"))
        payload = json.loads(data[5:])
        assert set(payload["AAPL"]) == {"ticker", "price", "previous_price", "timestamp",
                                        "direction", "change_percent"}


# --- chat -------------------------------------------------------------------------

def test_chat_mock_buy(client):
    r = client.post("/api/chat", json={"message": "please buy 5 aapl now"})
    body = r.json()
    assert r.status_code == 200 and body["role"] == "assistant"
    assert body["content"] == "Buying 5 AAPL."
    t = body["actions"]["trades"][0]
    assert t["status"] == "executed" and t["ticker"] == "AAPL" and t["price"] > 0
    assert client.get("/api/portfolio").json()["positions"][0]["quantity"] == 5


def test_chat_failed_action_reported(client):
    body = client.post("/api/chat", json={"message": "sell 3 TSLA"}).json()
    t = body["actions"]["trades"][0]
    assert t["status"] == "failed" and t["error"].startswith("Insufficient shares")
    body = client.post("/api/chat", json={"message": "remove IBM"}).json()
    assert body["actions"]["watchlist_changes"][0]["status"] == "failed"


def test_chat_add_remove_and_history(client):
    client.post("/api/chat", json={"message": "add pypl"})
    assert "PYPL" in [w["ticker"] for w in client.get("/api/watchlist").json()]
    client.post("/api/chat", json={"message": "remove PYPL"})
    assert "PYPL" not in [w["ticker"] for w in client.get("/api/watchlist").json()]
    hist = client.get("/api/chat/history").json()
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    assert hist[0]["actions"] is None and hist[0]["content"] == "add pypl"


def test_chat_failure_path(client):
    body = client.post("/api/chat", json={"message": "please fail"}).json()
    assert body["content"] == "Sorry, I couldn't process that request. Please try again."
    assert body["actions"] == {"trades": [], "watchlist_changes": []}
    assert len(client.get("/api/chat/history").json()) == 2


def test_chat_default_reply(client):
    body = client.post("/api/chat", json={"message": "hello"}).json()
    assert body["content"] == "This is a mock response from trading_workstation."


def test_chat_without_key(no_key_client):
    body = no_key_client.post("/api/chat", json={"message": "hi"}).json()
    assert "isn't configured" in body["content"]


def test_structured_parsing():
    parsed = LLMResponse.model_validate_json(mock_completion("buy 2.5 brk.b"))
    assert parsed.trades[0].ticker == "BRK.B" and parsed.trades[0].quantity == 2.5
    with pytest.raises(Exception):
        LLMResponse.model_validate_json('{"message": "hi"}')
    with pytest.raises(Exception):
        LLMResponse.model_validate_json('{"message":"x","trades":[{"ticker":"A","side":"hold","quantity":1}],"watchlist_changes":[]}')
    with pytest.raises(Exception):
        LLMResponse.model_validate_json("not json")


def test_summarize_actions():
    s = summarize_actions({
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed",
                    "price": 190.12, "error": None}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "failed",
                               "error": "Unknown ticker"}],
    })
    assert s == "[Actions: add PYPL failed: Unknown ticker; buy 10 AAPL @ 190.12 executed]"
