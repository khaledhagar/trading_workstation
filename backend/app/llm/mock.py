"""Deterministic mock LLM for LLM_MOCK=true (PLAN.md §9 "LLM Mock Mode").

It replaces only the LLM call: it returns the raw JSON text a real model would, which then goes
through the same parsing, execution and persistence path. Rules are case-insensitive, checked in
order, first match wins, and may appear anywhere in the message.
"""

import json
import re

_QTY = r"(\d+(?:\.\d+)?)"
_TICKER = r"([A-Za-z.]+)"

_BUY = re.compile(rf"\bbuy\s+{_QTY}\s+{_TICKER}", re.IGNORECASE)
_SELL = re.compile(rf"\bsell\s+{_QTY}\s+{_TICKER}", re.IGNORECASE)
_ADD = re.compile(rf"\badd\s+{_TICKER}", re.IGNORECASE)
_REMOVE = re.compile(rf"\bremove\s+{_TICKER}", re.IGNORECASE)
_FAIL = re.compile(r"fail", re.IGNORECASE)

DEFAULT_MESSAGE = "This is a mock response from trading_workstation."


class MockLLMFailure(RuntimeError):
    """Raised for messages containing "fail", to exercise the failure-handling path."""


def _ticker(raw: str) -> str:
    # A sentence-ending period ("buy 5 AAPL.") isn't part of the ticker; inner dots (BRK.B) are.
    return raw.rstrip(".").upper() or raw.upper()


def _qty(raw: str) -> float:
    return float(raw)


def mock_response(message: str) -> str:
    """Return the mock model's raw JSON output for `message`, or raise MockLLMFailure."""
    trades: list[dict] = []
    changes: list[dict] = []

    if m := _BUY.search(message):
        qty, ticker = m.group(1), _ticker(m.group(2))
        text = f"Buying {qty} {ticker}."
        trades.append({"ticker": ticker, "side": "buy", "quantity": _qty(qty)})
    elif m := _SELL.search(message):
        qty, ticker = m.group(1), _ticker(m.group(2))
        text = f"Selling {qty} {ticker}."
        trades.append({"ticker": ticker, "side": "sell", "quantity": _qty(qty)})
    elif m := _ADD.search(message):
        ticker = _ticker(m.group(1))
        text = f"Adding {ticker} to your watchlist."
        changes.append({"ticker": ticker, "action": "add"})
    elif m := _REMOVE.search(message):
        ticker = _ticker(m.group(1))
        text = f"Removing {ticker} from your watchlist."
        changes.append({"ticker": ticker, "action": "remove"})
    elif _FAIL.search(message):
        raise MockLLMFailure("Simulated LLM failure (mock)")
    else:
        text = DEFAULT_MESSAGE

    return json.dumps({"message": text, "trades": trades, "watchlist_changes": changes})
