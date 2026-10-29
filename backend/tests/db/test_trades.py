import threading
import time

import pytest

import db


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def state(conn):
    return (
        db.get_cash(conn),
        db.list_positions(conn),
        count(conn, "trades"),
        count(conn, "portfolio_snapshots"),
    )


def buy(conn, prices, ticker, qty):
    return db.execute_trade(conn, ticker=ticker, side="buy", quantity=qty, get_price=prices.get_price)


def sell(conn, prices, ticker, qty):
    return db.execute_trade(conn, ticker=ticker, side="sell", quantity=qty, get_price=prices.get_price)


def test_buy_basic(conn, prices):
    t = buy(conn, prices, "AAPL", 10)
    assert set(t) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert t["ticker"] == "AAPL" and t["side"] == "buy" and t["quantity"] == 10 and t["price"] == 190.0
    assert t["executed_at"].endswith("Z")
    assert db.get_cash(conn) == 8100.0
    pos = db.get_position(conn, "AAPL")
    assert pos["quantity"] == 10 and pos["avg_cost"] == 190.0
    assert pos["updated_at"].endswith("Z")
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert (row["id"], row["user_id"], row["ticker"], row["side"], row["quantity"], row["price"]) == (
        t["id"], "default", "AAPL", "buy", 10, 190.0)


def test_buy_normalizes_ticker(conn, prices):
    t = buy(conn, prices, " aapl ", 1)
    assert t["ticker"] == "AAPL"
    assert db.get_position(conn, "aapl")["quantity"] == 1


def test_weighted_avg_cost(conn, prices):
    buy(conn, prices, "AAPL", 10)  # @190
    prices["AAPL"] = 200.0
    buy(conn, prices, "AAPL", 5)
    pos = db.get_position(conn, "AAPL")
    assert pos["quantity"] == 15
    assert pos["avg_cost"] == pytest.approx((10 * 190 + 5 * 200) / 15)
    assert db.get_cash(conn) == 10000 - 1900 - 1000


def test_sell_keeps_avg_cost_and_credits_cash(conn, prices):
    buy(conn, prices, "AAPL", 10)
    prices["AAPL"] = 180.0  # sell at a loss
    t = sell(conn, prices, "AAPL", 4)
    assert t["side"] == "sell" and t["price"] == 180.0
    pos = db.get_position(conn, "AAPL")
    assert pos["quantity"] == 6 and pos["avg_cost"] == 190.0
    assert db.get_cash(conn) == 8100.0 + 720.0


def test_full_exit_deletes_row_and_rebuy_is_fresh(conn, prices):
    buy(conn, prices, "AAPL", 10)
    sell(conn, prices, "AAPL", 10)
    assert db.get_position(conn, "AAPL") is None
    assert db.list_positions(conn) == []
    assert db.get_cash(conn) == 10000.0
    prices["AAPL"] = 100.0
    buy(conn, prices, "AAPL", 1)
    assert db.get_position(conn, "AAPL")["avg_cost"] == 100.0


def test_fractional_full_exit_with_float_noise(conn, prices):
    buy(conn, prices, "AAPL", 0.1)
    buy(conn, prices, "AAPL", 0.2)
    assert db.get_position(conn, "AAPL")["quantity"] == 0.3
    sell(conn, prices, "AAPL", 0.3)
    assert db.get_position(conn, "AAPL") is None


def test_quantity_rounded_to_4dp(conn, prices):
    t = buy(conn, prices, "AAPL", 1.23456)
    assert t["quantity"] == 1.2346
    assert db.get_position(conn, "AAPL")["quantity"] == 1.2346


def test_cash_rounded_to_2dp(conn, prices):
    prices["AAPL"] = 190.123
    buy(conn, prices, "AAPL", 3)  # 570.369
    assert db.get_cash(conn) == round(10000 - 570.369, 2)


def test_buy_exact_cash_allowed(conn, prices):
    prices["AAPL"] = 1000.0
    buy(conn, prices, "AAPL", 10)
    assert db.get_cash(conn) == 0.0


def test_insufficient_cash_message_and_unchanged(conn, prices):
    conn.execute("UPDATE users_profile SET cash_balance = 500")
    prices["AAPL"] = 190.12
    before = state(conn)
    with pytest.raises(db.TradeError) as e:
        buy(conn, prices, "AAPL", 10)
    assert str(e.value) == "Insufficient cash: need $1,901.20, have $500.00"
    assert isinstance(e.value, ValueError)
    assert state(conn) == before
    assert not conn.in_transaction


def test_insufficient_cash_thousands(conn, prices):
    prices["MSFT"] = 400.0
    with pytest.raises(db.TradeError) as e:
        buy(conn, prices, "MSFT", 100)
    assert str(e.value) == "Insufficient cash: need $40,000.00, have $10,000.00"


def test_insufficient_shares_message(conn, prices):
    buy(conn, prices, "AAPL", 5)
    before = state(conn)
    with pytest.raises(db.TradeError) as e:
        sell(conn, prices, "AAPL", 10)
    assert str(e.value) == "Insufficient shares: have 5, tried to sell 10"
    assert state(conn) == before


def test_insufficient_shares_fractional_and_not_held(conn, prices):
    buy(conn, prices, "AAPL", 2.5)
    with pytest.raises(db.TradeError) as e:
        sell(conn, prices, "AAPL", 2.75)
    assert str(e.value) == "Insufficient shares: have 2.5, tried to sell 2.75"
    with pytest.raises(db.TradeError) as e:
        sell(conn, prices, "TSLA", 1)
    assert str(e.value) == "Insufficient shares: have 0, tried to sell 1"


def test_no_price(conn, prices):
    before = state(conn)
    with pytest.raises(db.TradeError) as e:
        buy(conn, prices, "NOPE", 1)
    assert str(e.value) == "No price available for NOPE yet"
    assert state(conn) == before


def test_invalid_side_and_quantity(conn, prices):
    with pytest.raises(ValueError):
        db.execute_trade(conn, ticker="AAPL", side="short", quantity=1, get_price=prices.get_price)
    with pytest.raises(ValueError):
        buy(conn, prices, "AAPL", 0)
    with pytest.raises(ValueError):
        buy(conn, prices, "AAPL", -1)
    assert not conn.in_transaction


def test_price_read_inside_transaction(conn, prices):
    seen = []

    def get_price(t):
        seen.append(conn.in_transaction)
        return prices.get_price(t)

    db.execute_trade(conn, ticker="AAPL", side="buy", quantity=1, get_price=get_price)
    assert seen and all(seen)


def test_snapshot_inserted_with_total_value(conn, prices):
    buy(conn, prices, "AAPL", 10)  # cash 8100, AAPL 10 @190
    snaps = db.list_snapshots(conn)
    assert len(snaps) == 1 and snaps[0]["total_value"] == 10000.0
    prices["AAPL"] = 200.0
    buy(conn, prices, "MSFT", 1)  # cash 7700; AAPL 10*200 + MSFT 400
    assert db.list_snapshots(conn)[-1]["total_value"] == 7700 + 2000 + 400


def test_snapshot_falls_back_to_avg_cost(conn, prices):
    buy(conn, prices, "AAPL", 10)  # 1900 at cost
    del prices.prices["AAPL"]
    buy(conn, prices, "MSFT", 1)  # cash 7700, MSFT 400, AAPL valued at avg_cost 1900
    assert db.list_snapshots(conn)[-1]["total_value"] == 10000.0


def test_rollback_on_unexpected_error(conn, prices):
    buy(conn, prices, "MSFT", 1)
    before = state(conn)

    def get_price(t):
        if t == "MSFT":  # called during snapshot valuation, after the writes
            raise RuntimeError("boom")
        return prices.get_price(t)

    with pytest.raises(RuntimeError):
        db.execute_trade(conn, ticker="AAPL", side="buy", quantity=1, get_price=get_price)
    assert state(conn) == before
    assert not conn.in_transaction


def test_trades_append_only_log(conn, prices):
    buy(conn, prices, "AAPL", 2)
    sell(conn, prices, "AAPL", 1)
    buy(conn, prices, "TSLA", 1)
    rows = conn.execute("SELECT ticker, side, quantity FROM trades ORDER BY rowid").fetchall()
    assert [tuple(r) for r in rows] == [("AAPL", "buy", 2), ("AAPL", "sell", 1), ("TSLA", "buy", 1)]
    assert count(conn, "portfolio_snapshots") == 3


def test_concurrent_trades_cannot_overdraw(db_path, prices):
    """Two connections each try to spend $6,000 of $10,000; exactly one must succeed."""
    prices["AAPL"] = 600.0
    barrier = threading.Barrier(2)
    results: list = []

    def slow_price(t):
        time.sleep(0.2)  # hold the write lock while the other thread is trying
        return prices.get_price(t)

    def worker():
        with db.connect(db_path) as c:
            barrier.wait()
            try:
                db.execute_trade(c, ticker="AAPL", side="buy", quantity=10, get_price=slow_price)
                results.append("ok")
            except db.TradeError as e:
                results.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert sorted(results) == ["Insufficient cash: need $6,000.00, have $4,000.00", "ok"]
    with db.connect(db_path) as c:
        assert db.get_cash(c) == 4000.0
        assert db.get_position(c, "AAPL")["quantity"] == 10
        assert count(c, "trades") == 1


def test_concurrent_sells_cannot_oversell(db_path, prices):
    with db.connect(db_path) as c:
        buy(c, prices, "AAPL", 10)
    barrier = threading.Barrier(4)
    results: list = []

    def worker():
        with db.connect(db_path) as c:
            barrier.wait()
            try:
                sell(c, prices, "AAPL", 4)
                results.append("ok")
            except db.TradeError as e:
                results.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count("ok") == 2
    with db.connect(db_path) as c:
        assert db.get_position(c, "AAPL")["quantity"] == 2
        assert db.get_cash(c) == 10000.0 - 1900 + 8 * 190
