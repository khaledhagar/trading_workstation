import json
import re

import db


# ---------------------------------------------------------------- watchlist / tracked


def test_add_watchlist_new_and_duplicate(conn):
    assert db.add_watchlist(conn, "PYPL") is True
    assert db.add_watchlist(conn, "PYPL") is False
    assert db.list_watchlist(conn)[-1] == "PYPL"
    assert db.list_watchlist(conn).count("PYPL") == 1


def test_add_watchlist_order_by_added_at(conn):
    for t in ["ZZZ", "BBB", "AAA"]:
        db.add_watchlist(conn, t)
    assert db.list_watchlist(conn)[-3:] == ["ZZZ", "BBB", "AAA"]


def test_add_watchlist_monotonic_even_with_future_rows(conn):
    conn.execute("INSERT INTO watchlist VALUES ('default', 'FUT', '2999-01-01T00:00:00.000Z')")
    db.add_watchlist(conn, "AAA")
    assert db.list_watchlist(conn)[-2:] == ["FUT", "AAA"]
    row = conn.execute("SELECT added_at FROM watchlist WHERE ticker='AAA'").fetchone()
    assert row["added_at"] == "2999-01-01T00:00:00.001Z"


def test_remove_watchlist(conn):
    assert db.remove_watchlist(conn, "AAPL") is True
    assert db.remove_watchlist(conn, "AAPL") is False
    assert "AAPL" not in db.list_watchlist(conn)


def test_watchlist_normalizes_case(conn):
    assert db.add_watchlist(conn, " pypl ") is True
    assert "PYPL" in db.list_watchlist(conn)
    assert db.remove_watchlist(conn, "pypl") is True


def test_tracked_tickers_union(conn, prices):
    db.execute_trade(conn, ticker="AAPL", side="buy", quantity=1, get_price=prices.get_price)
    db.remove_watchlist(conn, "AAPL")
    prices["XYZ"] = 10.0
    db.execute_trade(conn, ticker="XYZ", side="buy", quantity=1, get_price=prices.get_price)
    tracked = db.tracked_tickers(conn)
    assert "AAPL" in tracked and "XYZ" in tracked and "MSFT" in tracked
    assert len(tracked) == 11
    db.execute_trade(conn, ticker="AAPL", side="sell", quantity=1, get_price=prices.get_price)
    assert "AAPL" not in db.tracked_tickers(conn)


def test_user_isolation(conn):
    conn.execute("INSERT INTO users_profile (id, cash_balance, created_at) VALUES ('u2', 5, 'x')")
    db.add_watchlist(conn, "PYPL", user_id="u2")
    assert db.list_watchlist(conn, user_id="u2") == ["PYPL"]
    assert "PYPL" not in db.list_watchlist(conn)
    assert db.get_cash(conn, user_id="u2") == 5.0
    assert db.get_cash(conn, user_id="nobody") == 0.0


# ---------------------------------------------------------------- snapshots


def test_snapshots_order_and_limit(conn):
    for v in range(1, 6):
        db.insert_snapshot(conn, v * 1000.123)
    snaps = db.list_snapshots(conn)
    assert [s["total_value"] for s in snaps] == [round(v * 1000.123, 2) for v in range(1, 6)]
    assert set(snaps[0]) == {"total_value", "recorded_at"}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", snaps[0]["recorded_at"])
    last2 = db.list_snapshots(conn, limit=2)
    assert [s["total_value"] for s in last2] == [round(4000.492, 2), round(5000.615, 2)]


def test_snapshots_default_limit_1000(conn):
    conn.execute("BEGIN")
    for v in range(1100):
        db.insert_snapshot(conn, v)
    conn.execute("COMMIT")
    snaps = db.list_snapshots(conn)
    assert len(snaps) == 1000
    assert snaps[0]["total_value"] == 100
    assert snaps[-1]["total_value"] == 1099


def test_snapshots_order_by_time_not_insertion(conn):
    conn.execute("INSERT INTO portfolio_snapshots VALUES ('a','default',2,'2026-01-01T12:00:10Z')")
    conn.execute("INSERT INTO portfolio_snapshots VALUES ('b','default',1,'2026-01-01T12:00:00Z')")
    assert [s["total_value"] for s in db.list_snapshots(conn)] == [1, 2]


# ---------------------------------------------------------------- chat


def test_chat_insert_and_list(conn):
    u = db.insert_chat_message(conn, "user", "Buy 10 AAPL", None)
    actions = {"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed",
                           "price": 190.12, "error": None}], "watchlist_changes": []}
    a = db.insert_chat_message(conn, "assistant", "Placing an order…", actions)
    assert set(u) == {"id", "role", "content", "actions", "created_at"}
    assert u["actions"] is None and a["actions"] == actions
    msgs = db.list_chat_messages(conn)
    assert [m["id"] for m in msgs] == [u["id"], a["id"]]
    assert msgs[1]["actions"] == actions
    assert msgs[0]["actions"] is None
    raw = conn.execute("SELECT actions FROM chat_messages WHERE id=?", (a["id"],)).fetchone()[0]
    assert json.loads(raw) == actions


def test_chat_limit_most_recent_oldest_first(conn):
    for i in range(60):
        db.insert_chat_message(conn, "user" if i % 2 == 0 else "assistant", f"m{i}", None)
    msgs = db.list_chat_messages(conn)
    assert len(msgs) == 50
    assert msgs[0]["content"] == "m10" and msgs[-1]["content"] == "m59"
    msgs20 = db.list_chat_messages(conn, limit=20)
    assert [m["content"] for m in msgs20] == [f"m{i}" for i in range(40, 60)]


def test_chat_invalid_role(conn):
    import pytest
    with pytest.raises(ValueError):
        db.insert_chat_message(conn, "system", "x", None)
