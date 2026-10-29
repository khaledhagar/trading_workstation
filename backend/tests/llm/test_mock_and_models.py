import json

import pytest
from pydantic import ValidationError

from app.llm.mock import DEFAULT_MESSAGE, MockLLMFailure, mock_response
from app.llm.models import LLMResponse


def parse(msg: str) -> LLMResponse:
    return LLMResponse.model_validate_json(mock_response(msg))


# --- mock rules -------------------------------------------------------------

def test_buy_rule():
    r = parse("buy 5 AAPL")
    assert r.message == "Buying 5 AAPL."
    assert [t.model_dump() for t in r.trades] == [{"ticker": "AAPL", "side": "buy", "quantity": 5.0}]
    assert r.watchlist_changes == []


def test_sell_rule_case_insensitive_and_anywhere():
    r = parse("Please SELL 2 msft now")
    assert r.message == "Selling 2 MSFT."
    assert r.trades[0].side == "sell" and r.trades[0].ticker == "MSFT" and r.trades[0].quantity == 2


def test_decimal_quantity():
    r = parse("buy 1.5 nvda")
    assert r.message == "Buying 1.5 NVDA."
    assert r.trades[0].quantity == 1.5


def test_dotted_ticker_and_trailing_period():
    r = parse("buy 3 brk.b.")
    assert r.trades[0].ticker == "BRK.B"
    assert r.message == "Buying 3 BRK.B."


def test_add_rule():
    r = parse("add pypl")
    assert r.message == "Adding PYPL to your watchlist."
    assert [c.model_dump() for c in r.watchlist_changes] == [{"ticker": "PYPL", "action": "add"}]
    assert r.trades == []


def test_remove_rule():
    r = parse("remove TSLA")
    assert r.message == "Removing TSLA from your watchlist."
    assert r.watchlist_changes[0].action == "remove"


def test_fail_rule():
    with pytest.raises(MockLLMFailure):
        mock_response("please FAIL")


def test_default_rule():
    r = parse("how is my portfolio?")
    assert r.message == DEFAULT_MESSAGE
    assert r.trades == [] and r.watchlist_changes == []


def test_ordering_first_match_wins():
    # buy beats sell/add/fail even when it appears later in the message
    assert parse("add PYPL then buy 1 AAPL").trades[0].ticker == "AAPL"
    assert parse("sell 1 AAPL and add PYPL").watchlist_changes == []
    # add beats remove and fail
    assert parse("remove TSLA, add PYPL").watchlist_changes[0].action == "add"
    assert parse("add PYPL or fail").message.startswith("Adding")


def test_buy_without_quantity_is_not_a_trade():
    assert parse("buy AAPL").message == DEFAULT_MESSAGE


# --- schema -----------------------------------------------------------------

def test_schema_valid():
    r = LLMResponse.model_validate_json(json.dumps({
        "message": "hi",
        "trades": [{"ticker": "AAPL", "side": "sell", "quantity": 0.25}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "remove"}],
    }))
    assert r.trades[0].quantity == 0.25


@pytest.mark.parametrize("raw", [
    "not json",
    '{"message": "hi"}',                                                       # missing arrays
    '{"message": "hi", "trades": [], "watchlist_changes": [{"ticker": "A", "action": "buy"}]}',
    '{"message": "hi", "trades": [{"ticker": "A", "side": "hold", "quantity": 1}], "watchlist_changes": []}',
    '{"message": "hi", "trades": [{"ticker": "A", "side": "buy"}], "watchlist_changes": []}',
    '{"message": 5, "trades": [], "watchlist_changes": []}',
])
def test_schema_malformed(raw):
    with pytest.raises(ValidationError):
        LLMResponse.model_validate_json(raw)


def test_schema_marks_everything_required_and_enums():
    schema = LLMResponse.model_json_schema()
    assert set(schema["required"]) == {"message", "trades", "watchlist_changes"}
    trade = schema["$defs"]["TradeAction"]
    assert set(trade["required"]) == {"ticker", "side", "quantity"}
    assert trade["properties"]["side"]["enum"] == ["buy", "sell"]
    assert schema["$defs"]["WatchlistChange"]["properties"]["action"]["enum"] == ["add", "remove"]
