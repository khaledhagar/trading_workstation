"""Chat flow (PLAN.md §9 "How It Works"): context → LLM (or mock) → parse → execute actions → persist."""

import logging
import math
from decimal import Decimal, InvalidOperation

import db
from app.market import InvalidTickerError, MarketDataUnavailableError, normalize_ticker
from app.services import add_ticker, build_portfolio, remove_ticker, trade, watchlist_rows

from . import client
from .mock import mock_response
from .models import LLMResponse, TradeAction, WatchlistChange
from .prompt import HISTORY_LIMIT, build_messages

log = logging.getLogger(__name__)

NOT_CONFIGURED_MESSAGE = "The AI assistant isn't configured. Set OPENROUTER_API_KEY in .env and restart."
FAILURE_MESSAGE = "Sorry, I couldn't process that request. Please try again."
MARKET_UNAVAILABLE = "Market data unavailable, try again shortly"


def _empty(message: str) -> LLMResponse:
    return LLMResponse(message=message, trades=[], watchlist_changes=[])


def _qty_out(q: float) -> float | int:
    return int(q) if math.isfinite(q) and float(q).is_integer() else q


def quantity_error(q: float) -> str | None:
    """Same rule as the trade route's request model: > 0 and at most 4 decimal places."""
    if not math.isfinite(q) or q <= 0:
        return "Quantity must be greater than 0"
    try:
        exponent = Decimal(str(q)).normalize().as_tuple().exponent
    except InvalidOperation:
        return "Invalid quantity"
    if isinstance(exponent, int) and exponent < -4:
        return "Quantity can have at most 4 decimal places"
    return None


def _error_text(exc: Exception) -> str:
    if isinstance(exc, MarketDataUnavailableError):
        return MARKET_UNAVAILABLE
    return str(exc) or exc.__class__.__name__


def _display_ticker(raw: str) -> str:
    try:
        return normalize_ticker(raw)
    except InvalidTickerError:
        return raw.strip() if isinstance(raw, str) else str(raw)


async def _apply_change(state, change: WatchlistChange) -> dict:
    out = {"ticker": _display_ticker(change.ticker), "action": change.action, "status": "executed", "error": None}
    try:
        if change.action == "add":
            await add_ticker(state, change.ticker)
        else:
            await remove_ticker(state, change.ticker)
    except Exception as exc:  # each action is independent; report and move on
        if not isinstance(exc, (ValueError, LookupError, MarketDataUnavailableError)):
            log.exception("Unexpected error applying watchlist change %s", change)
        out.update(status="failed", error=_error_text(exc))
    return out


async def _apply_trade(state, t: TradeAction) -> dict:
    out = {"ticker": _display_ticker(t.ticker), "side": t.side, "quantity": _qty_out(t.quantity),
           "status": "executed", "price": None, "error": None}
    if err := quantity_error(t.quantity):
        out.update(status="failed", error=err)
        return out
    try:
        result = await trade(state, t.ticker, t.side, t.quantity)
        out["price"] = result["trade"]["price"]
    except Exception as exc:
        if not isinstance(exc, (ValueError, LookupError, MarketDataUnavailableError)):
            log.exception("Unexpected error executing trade %s", t)
        out.update(status="failed", error=_error_text(exc))
    return out


async def _ask_llm(state, message: str) -> LLMResponse:
    """The LLM step. Never raises: failures and invalid output become the apology message."""
    mock = client.mock_enabled()
    if not mock and not client.api_key():
        return _empty(NOT_CONFIGURED_MESSAGE)
    try:
        if mock:
            raw = mock_response(message)
        else:
            cache = state.price_cache
            with db.connect() as conn:
                portfolio = build_portfolio(conn, cache)
                watchlist = watchlist_rows(conn, cache)
                history = db.list_chat_messages(conn, limit=HISTORY_LIMIT)
            raw = await client.complete(build_messages(portfolio, watchlist, history, message))
        return LLMResponse.model_validate_json(raw)
    except Exception:
        log.exception("LLM call failed or returned invalid output")
        return _empty(FAILURE_MESSAGE)


async def handle_chat(state, message: str) -> dict:
    """Full POST /api/chat response. Never raises for LLM failures."""
    response = await _ask_llm(state, message)

    # PLAN.md §8 Chat ordering: watchlist changes before trades.
    changes = [await _apply_change(state, c) for c in response.watchlist_changes]
    trades = [await _apply_trade(state, t) for t in response.trades]
    actions = {"trades": trades, "watchlist_changes": changes}

    with db.connect() as conn:
        db.insert_chat_message(conn, "user", message, None)
        return db.insert_chat_message(conn, "assistant", response.message, actions)


def chat_history(limit: int = 50) -> list[dict]:
    with db.connect() as conn:
        return db.list_chat_messages(conn, limit=limit)
