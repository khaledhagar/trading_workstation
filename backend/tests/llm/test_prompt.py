from app.llm.prompt import SYSTEM_PROMPT, build_messages, fmt_qty, history_messages, summarize_actions


def test_fmt_qty():
    assert fmt_qty(10.0) == "10"
    assert fmt_qty(0.5) == "0.5"
    assert fmt_qty(1.23456) == "1.2346"


def test_summary_matches_plan_example():
    actions = {
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed", "price": 190.12,
                    "error": None}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "failed", "error": "Unknown ticker"}],
    }
    assert summarize_actions(actions) == "[Actions: add PYPL failed: Unknown ticker; buy 10 AAPL @ 190.12 executed]"


def test_summary_failed_trade_and_empty():
    actions = {"trades": [{"ticker": "TSLA", "side": "sell", "quantity": 2.5, "status": "failed", "price": None,
                           "error": "Insufficient shares: have 0, tried to sell 2.5"}], "watchlist_changes": []}
    assert summarize_actions(actions) == "[Actions: sell 2.5 TSLA failed: Insufficient shares: have 0, tried to sell 2.5]"
    assert summarize_actions({"trades": [], "watchlist_changes": []}) == ""
    assert summarize_actions(None) == ""


def test_history_appends_summary_to_assistant_only():
    hist = [
        {"role": "user", "content": "buy 1 AAPL", "actions": None},
        {"role": "assistant", "content": "Placing an order.", "actions": {
            "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1, "status": "executed", "price": 190.0}],
            "watchlist_changes": []}},
        {"role": "assistant", "content": "Hello", "actions": {"trades": [], "watchlist_changes": []}},
    ]
    out = history_messages(hist)
    assert out[0] == {"role": "user", "content": "buy 1 AAPL"}
    assert out[1]["content"] == "Placing an order.\n[Actions: buy 1 AAPL @ 190.00 executed]"
    assert out[2]["content"] == "Hello"


def test_history_capped_at_20():
    hist = [{"role": "user", "content": str(i), "actions": None} for i in range(30)]
    out = history_messages(hist)
    assert len(out) == 20 and out[0]["content"] == "10" and out[-1]["content"] == "29"


def test_build_messages_includes_context():
    portfolio = {"cash_balance": 8098.8, "positions_value": 1905.0, "total_value": 10003.8, "unrealized_pnl": 3.8,
                 "positions": [{"ticker": "AAPL", "quantity": 10, "avg_cost": 190.12, "current_price": 190.5,
                                "market_value": 1905.0, "unrealized_pnl": 3.8, "pnl_percent": 0.2}]}
    watchlist = [{"ticker": "AAPL", "price": 190.5, "change_percent": 0.48}, {"ticker": "PYPL", "price": None}]
    msgs = build_messages(portfolio, watchlist, [], "how am I doing?")
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT}
    ctx = msgs[1]["content"]
    for needle in ("$8,098.80", "$10,003.80", "AAPL: qty 10", "+0.20%", "PYPL: no price yet", "+0.48%"):
        assert needle in ctx
    assert msgs[-1] == {"role": "user", "content": "how am I doing?"}
    assert "trading_workstation" in SYSTEM_PROMPT
