"""LLM chat: context building, structured output, mock mode and action execution (PLAN.md §9)."""

import json
import logging
import re
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from . import config, db
from .market import InvalidTickerError, MarketDataUnavailableError, UnknownTickerError
from .portfolio import (
    NotWatchedError,
    TradeError,
    add_to_watchlist,
    execute_trade,
    portfolio_payload,
    remove_from_watchlist,
    watchlist_payload,
)

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
LLM_TIMEOUT = 30.0
HISTORY_FOR_LLM = 20
HISTORY_FOR_UI = 50

FAILURE_MESSAGE = "Sorry, I couldn't process that request. Please try again."
NOT_CONFIGURED_MESSAGE = (
    "The AI assistant isn't configured. Set OPENROUTER_API_KEY in .env and restart."
)
UNAVAILABLE_MESSAGE = "Market data unavailable, try again shortly"


# --- structured output schema ---------------------------------------------------

class TradeRequest(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: Literal["add", "remove"]


class LLMResponse(BaseModel):
    message: str
    trades: list[TradeRequest]
    watchlist_changes: list[WatchlistChange]


class LLMFailure(Exception):
    pass


SYSTEM_PROMPT = """You are trading_workstation, an AI trading assistant inside a simulated trading terminal.
The user trades a simulated portfolio with fake money using instant market orders (no fees, fractional shares up to 4 decimals).

Your job:
- Analyze portfolio composition, risk concentration and P&L using the context provided.
- Suggest trades with brief reasoning when useful.
- Execute trades only when the user explicitly asks for them or agrees to a suggestion. Suggestions go in `message`, never in `trades`.
- Manage the watchlist proactively when the user asks (add/remove tickers).
- Be concise and data-driven. Use numbers from the context; never invent prices.

Response format: always reply with JSON matching the schema, with fields `message`, `trades` and `watchlist_changes`. Use empty arrays when there is nothing to do.
Your message is written BEFORE actions run, so phrase trades and watchlist changes as actions being taken ("Placing an order to buy 10 AAPL..."), not as confirmed results. The real outcomes are shown to the user separately, and you will see them in the conversation history as [Actions: ...] notes."""


# --- context ---------------------------------------------------------------------

def _portfolio_context(app: FastAPI) -> str:
    p = portfolio_payload(app)
    lines = [
        f"Cash: ${p['cash_balance']:,.2f}",
        f"Positions value: ${p['positions_value']:,.2f}",
        f"Total portfolio value: ${p['total_value']:,.2f}",
        f"Unrealized P&L: ${p['unrealized_pnl']:,.2f}",
        "Positions:" if p["positions"] else "Positions: none",
    ]
    total = p["total_value"] or 1
    for pos in p["positions"]:
        weight = pos["market_value"] / total * 100
        lines.append(
            f"- {pos['ticker']}: {pos['quantity']} sh, avg ${pos['avg_cost']:.2f}, "
            f"now ${pos['current_price']:.2f}, value ${pos['market_value']:,.2f} ({weight:.1f}% of portfolio), "
            f"P&L ${pos['unrealized_pnl']:,.2f} ({pos['pnl_percent']:+.2f}%)"
        )
    lines.append("Watchlist:")
    for w in watchlist_payload(app):
        if w["price"] is None:
            lines.append(f"- {w['ticker']}: no price yet")
        else:
            lines.append(f"- {w['ticker']}: ${w['price']:.2f} ({w['change_percent']:+.2f}% today)")
    return "\n".join(lines)


def summarize_actions(actions: dict | None) -> str:
    """Compact outcome summary, e.g. [Actions: buy 10 AAPL @ 190.12 executed; add PYPL failed: Unknown ticker]."""
    if not actions:
        return ""
    parts = []
    for c in actions.get("watchlist_changes") or []:
        s = f"{c['action']} {c['ticker']} {c['status']}"
        parts.append(s + (f": {c['error']}" if c.get("error") else ""))
    for t in actions.get("trades") or []:
        s = f"{t['side']} {t['quantity']} {t['ticker']}"
        if t.get("price") is not None:
            s += f" @ {t['price']}"
        s += f" {t['status']}"
        parts.append(s + (f": {t['error']}" if t.get("error") else ""))
    return f"[Actions: {'; '.join(parts)}]" if parts else ""


def _history_messages(limit: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM (SELECT id, role, content, actions, created_at FROM chat_messages "
            "WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?) "
            "ORDER BY created_at ASC",
            (db.DEFAULT_USER, limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "actions": json.loads(r["actions"]) if r["actions"] else None,
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def chat_history() -> list[dict]:
    return _history_messages(HISTORY_FOR_UI)


def build_messages(app: FastAPI, user_message: str) -> list[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "Current portfolio context:\n" + _portfolio_context(app)},
    ]
    for m in _history_messages(HISTORY_FOR_LLM):
        content = m["content"]
        if m["role"] == "assistant":
            summary = summarize_actions(m["actions"])
            if summary:
                content = f"{content}\n{summary}"
        messages.append({"role": m["role"], "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


# --- LLM call (real and mock) --------------------------------------------------

_QTY = r"(\d+(?:\.\d+)?)"
_TICKER = r"([A-Za-z.]+)"
MOCK_RULES = [
    ("buy", re.compile(rf"\bbuy\s+{_QTY}\s+{_TICKER}", re.I)),
    ("sell", re.compile(rf"\bsell\s+{_QTY}\s+{_TICKER}", re.I)),
    ("add", re.compile(rf"\badd\s+{_TICKER}", re.I)),
    ("remove", re.compile(rf"\bremove\s+{_TICKER}", re.I)),
    ("fail", re.compile(r"\bfail\b", re.I)),
]


def mock_completion(user_message: str) -> str:
    """Deterministic replacement for the LLM call. Returns raw JSON, like the real model."""
    for kind, pattern in MOCK_RULES:
        m = pattern.search(user_message)
        if not m:
            continue
        if kind in ("buy", "sell"):
            qty, ticker = m.group(1), m.group(2).upper()
            verb = "Buying" if kind == "buy" else "Selling"
            return json.dumps({
                "message": f"{verb} {qty} {ticker}.",
                "trades": [{"ticker": ticker, "side": kind, "quantity": float(qty)}],
                "watchlist_changes": [],
            })
        if kind in ("add", "remove"):
            ticker = m.group(1).upper()
            text = (f"Adding {ticker} to your watchlist." if kind == "add"
                    else f"Removing {ticker} from your watchlist.")
            return json.dumps({
                "message": text,
                "trades": [],
                "watchlist_changes": [{"ticker": ticker, "action": kind}],
            })
        raise LLMFailure("Mock LLM failure requested")
    return json.dumps({
        "message": "This is a mock response from trading_workstation.",
        "trades": [],
        "watchlist_changes": [],
    })


async def _call_llm(messages: list[dict]) -> str:
    from litellm import acompletion  # imported lazily: litellm is slow to import

    response = await acompletion(
        model=MODEL,
        messages=messages,
        response_format=LLMResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        timeout=LLM_TIMEOUT,
    )
    content = response.choices[0].message.content
    if not content:
        raise LLMFailure("Empty LLM response")
    return content


async def get_structured_response(app: FastAPI, user_message: str) -> LLMResponse:
    if config.llm_mock():
        raw = mock_completion(user_message)
    else:
        raw = await _call_llm(build_messages(app, user_message))
    return LLMResponse.model_validate_json(raw)


# --- action execution ------------------------------------------------------------

def _action_error(exc: Exception) -> str:
    if isinstance(exc, MarketDataUnavailableError):
        return UNAVAILABLE_MESSAGE
    return str(exc)


ACTION_ERRORS = (TradeError, NotWatchedError, InvalidTickerError, UnknownTickerError,
                 MarketDataUnavailableError)


async def execute_actions(app: FastAPI, parsed: LLMResponse) -> dict:
    """Watchlist changes first, then trades. Each action succeeds or fails independently."""
    changes = []
    for c in parsed.watchlist_changes:
        outcome = {"ticker": c.ticker.strip().upper(), "action": c.action, "status": "executed", "error": None}
        try:
            if c.action == "add":
                outcome["ticker"] = await add_to_watchlist(app, c.ticker)
            else:
                outcome["ticker"] = await remove_from_watchlist(app, c.ticker)
        except ACTION_ERRORS as exc:
            outcome.update(status="failed", error=_action_error(exc))
        except Exception:
            logger.exception("Watchlist action failed unexpectedly")
            outcome.update(status="failed", error="Unexpected error")
        changes.append(outcome)

    trades = []
    for t in parsed.trades:
        outcome = {"ticker": t.ticker.strip().upper(), "side": t.side, "quantity": t.quantity,
                   "status": "executed", "price": None, "error": None}
        try:
            result = await execute_trade(app, t.ticker, t.side, t.quantity)
            outcome.update(ticker=result["ticker"], quantity=result["quantity"], price=result["price"])
        except ACTION_ERRORS as exc:
            outcome.update(status="failed", error=_action_error(exc))
        except Exception:
            logger.exception("Trade action failed unexpectedly")
            outcome.update(status="failed", error="Unexpected error")
        trades.append(outcome)

    return {"trades": trades, "watchlist_changes": changes}


# --- persistence + entry point ---------------------------------------------------

def _store(role: str, content: str, actions: dict | None) -> dict:
    msg = {
        "id": db.new_id(),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": db.now_iso(),
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg["id"], db.DEFAULT_USER, role, content,
             json.dumps(actions) if actions is not None else None, msg["created_at"]),
        )
    return msg


EMPTY_ACTIONS = {"trades": [], "watchlist_changes": []}


async def handle_chat(app: FastAPI, user_message: str) -> dict:
    if not config.llm_mock() and not config.openrouter_key():
        _store("user", user_message, None)
        return _store("assistant", NOT_CONFIGURED_MESSAGE, dict(EMPTY_ACTIONS))

    try:
        parsed = await get_structured_response(app, user_message)
    except Exception:
        logger.exception("LLM call failed or returned an invalid response")
        _store("user", user_message, None)
        return _store("assistant", FAILURE_MESSAGE, dict(EMPTY_ACTIONS))

    # Store the user message before executing, so it sorts before the assistant reply.
    _store("user", user_message, None)
    actions = await execute_actions(app, parsed)
    return _store("assistant", parsed.message, actions)
