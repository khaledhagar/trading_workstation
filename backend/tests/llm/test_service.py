import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from app.api.chat import router
from app.llm import service
from app.llm.service import FAILURE_MESSAGE, NOT_CONFIGURED_MESSAGE, handle_chat, quantity_error


def history():
    with db.connect() as conn:
        return db.list_chat_messages(conn, limit=50)


# --- mock mode --------------------------------------------------------------

async def test_buy_executed(state, mock_llm):
    res = await handle_chat(state, "buy 10 AAPL")
    assert res["role"] == "assistant" and res["content"] == "Buying 10 AAPL."
    assert res["actions"]["trades"] == [
        {"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed", "price": 190.0, "error": None}]
    assert res["actions"]["watchlist_changes"] == []
    with db.connect() as conn:
        assert db.get_position(conn, "AAPL")["quantity"] == 10
        assert db.get_cash(conn) == 10000 - 1900
    h = history()
    assert [m["role"] for m in h] == ["user", "assistant"]
    assert h[0]["content"] == "buy 10 AAPL" and h[0]["actions"] is None
    assert h[1]["id"] == res["id"] and h[1]["actions"] == res["actions"]


async def test_insufficient_cash_failed(state, mock_llm):
    res = await handle_chat(state, "buy 1000 META")
    t = res["actions"]["trades"][0]
    assert t["status"] == "failed" and t["price"] is None
    assert t["error"].startswith("Insufficient cash: need $500,000.00")
    with db.connect() as conn:
        assert db.get_cash(conn) == 10000


async def test_unknown_ticker_add_failed(state, mock_llm):
    res = await handle_chat(state, "add ZZZZ")
    assert res["actions"]["watchlist_changes"] == [
        {"ticker": "ZZZZ", "action": "add", "status": "failed", "error": "Unknown ticker: ZZZZ"}]


async def test_add_and_remove(state, mock_llm):
    res = await handle_chat(state, "add PYPL")
    assert res["actions"]["watchlist_changes"][0]["status"] == "executed"
    res = await handle_chat(state, "remove PYPL")
    assert res["actions"]["watchlist_changes"][0]["status"] == "executed"
    res = await handle_chat(state, "remove PYPL")
    c = res["actions"]["watchlist_changes"][0]
    assert c["status"] == "failed" and "PYPL" in c["error"]


async def test_fail_path_stores_both_messages(state, mock_llm):
    res = await handle_chat(state, "fail")
    assert res["content"] == FAILURE_MESSAGE
    assert res["actions"] == {"trades": [], "watchlist_changes": []}
    h = history()
    assert [(m["role"], m["content"]) for m in h] == [("user", "fail"), ("assistant", FAILURE_MESSAGE)]


async def test_missing_key_does_not_call_llm(state, monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def boom(**kwargs):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(service.client.litellm, "acompletion", boom)
    res = await handle_chat(state, "buy 1 AAPL")
    assert res["content"] == NOT_CONFIGURED_MESSAGE
    assert res["actions"] == {"trades": [], "watchlist_changes": []}
    assert len(history()) == 2


# --- action independence & validation ----------------------------------------

def _fake_llm(monkeypatch, payload):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(service.client.litellm, "acompletion", fake)
    return calls


async def test_actions_are_independent_and_ordered(state, real_llm, monkeypatch):
    _fake_llm(monkeypatch, {
        "message": "Doing several things.",
        "trades": [
            {"ticker": "NOPE", "side": "buy", "quantity": 1},          # unknown ticker
            {"ticker": "pypl", "side": "buy", "quantity": 2},          # works only because add ran first
            {"ticker": "AAPL", "side": "sell", "quantity": 5},         # not held
            {"ticker": "MSFT", "side": "buy", "quantity": 0},          # bad quantity
            {"ticker": "MSFT", "side": "buy", "quantity": 1.23456},    # too many decimals
            {"ticker": "123", "side": "buy", "quantity": 1},           # invalid format
            {"ticker": "MSFT", "side": "buy", "quantity": 0.5},        # ok
        ],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add"}, {"ticker": "XXXX", "action": "add"}],
    })
    res = await handle_chat(state, "do it")
    changes = res["actions"]["watchlist_changes"]
    assert [c["status"] for c in changes] == ["executed", "failed"]
    trades = res["actions"]["trades"]
    assert [t["status"] for t in trades] == ["failed", "executed", "failed", "failed", "failed", "failed", "executed"]
    assert trades[0]["error"] == "Unknown ticker: NOPE"
    assert trades[1]["ticker"] == "PYPL" and trades[1]["price"] == 70.0
    assert trades[2]["error"].startswith("Insufficient shares")
    assert trades[3]["error"] == "Quantity must be greater than 0"
    assert trades[4]["error"] == "Quantity can have at most 4 decimal places"
    assert trades[5]["error"] == "Invalid ticker"
    assert trades[6]["quantity"] == 0.5 and trades[6]["price"] == 420.0


def test_quantity_error():
    assert quantity_error(1) is None
    assert quantity_error(0.0001) is None
    assert quantity_error(1.2345) is None
    assert quantity_error(0.00001) is not None
    assert quantity_error(-1) is not None
    assert quantity_error(float("nan")) is not None


# --- real client path (acompletion monkeypatched, no network) -----------------

async def test_real_client_valid_json(state, real_llm, monkeypatch):
    with db.connect() as conn:
        db.insert_chat_message(conn, "user", "earlier", None)
        db.insert_chat_message(conn, "assistant", "ok", {
            "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1, "status": "executed", "price": 190.0}],
            "watchlist_changes": []})
    calls = _fake_llm(monkeypatch, {"message": "Placing an order to buy 1 AAPL.",
                                    "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1}],
                                    "watchlist_changes": []})
    res = await handle_chat(state, "buy one apple share")
    assert res["actions"]["trades"][0]["status"] == "executed"

    kw = calls[0]
    assert kw["model"] == "openrouter/openai/gpt-oss-120b"
    assert kw["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert kw["reasoning_effort"] == "low"
    assert kw["response_format"] is service.LLMResponse
    assert kw["timeout"] == 30
    msgs = kw["messages"]
    assert msgs[0]["role"] == "system" and "Cash: $10,000.00" in msgs[1]["content"]
    assert msgs[2] == {"role": "user", "content": "earlier"}
    assert msgs[3]["content"] == "ok\n[Actions: buy 1 AAPL @ 190.00 executed]"
    assert msgs[-1] == {"role": "user", "content": "buy one apple share"}


async def test_real_client_invalid_json(state, real_llm, monkeypatch):
    _fake_llm(monkeypatch, '{"message": "hi", "trades": "nope"}')
    res = await handle_chat(state, "hello")
    assert res["content"] == FAILURE_MESSAGE
    assert res["actions"] == {"trades": [], "watchlist_changes": []}
    assert len(history()) == 2


async def test_real_client_exception(state, real_llm, monkeypatch):
    async def boom(**kwargs):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(service.client.litellm, "acompletion", boom)
    res = await handle_chat(state, "hello")
    assert res["content"] == FAILURE_MESSAGE
    assert [m["content"] for m in history()] == ["hello", FAILURE_MESSAGE]


# --- router -------------------------------------------------------------------

@pytest.fixture
def api(state):
    app = FastAPI()
    app.include_router(router)
    app.state.price_cache = state.price_cache
    app.state.market = state.market
    return TestClient(app)


def test_router_post_and_history(api, mock_llm):
    r = api.post("/api/chat", json={"message": "add PYPL"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "role", "content", "actions", "created_at"}
    assert body["actions"]["watchlist_changes"][0]["status"] == "executed"
    h = api.get("/api/chat/history").json()
    assert [m["role"] for m in h] == ["user", "assistant"]
    assert h[0]["actions"] is None


def test_router_validation(api, mock_llm):
    assert api.post("/api/chat", json={}).status_code == 422
    assert api.post("/api/chat", json={"message": ""}).status_code == 422


def test_history_limit_50(api, mock_llm):
    with db.connect() as conn:
        for i in range(60):
            db.insert_chat_message(conn, "user", f"m{i}", None)
    h = api.get("/api/chat/history").json()
    assert len(h) == 50 and h[0]["content"] == "m10" and h[-1]["content"] == "m59"
