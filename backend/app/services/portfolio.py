"""Portfolio valuation (PLAN.md §8 GET /api/portfolio)."""

import sqlite3

import db
from app.market import PriceCache


def build_portfolio(conn: sqlite3.Connection, cache: PriceCache) -> dict:
    """The exact GET /api/portfolio shape. Positions without a cached price are valued at avg_cost."""
    cash = db.get_cash(conn)
    positions = []
    positions_value = 0.0
    unrealized = 0.0
    for pos in db.list_positions(conn):
        qty, avg = pos["quantity"], pos["avg_cost"]
        price = cache.get_price(pos["ticker"])
        if price is None:
            price = avg
        value = qty * price
        pnl = (price - avg) * qty
        positions_value += value
        unrealized += pnl
        positions.append({
            "ticker": pos["ticker"],
            "quantity": round(qty, 4),
            "avg_cost": round(avg, 2),
            "current_price": round(price, 2),
            "market_value": round(value, 2),
            "unrealized_pnl": round(pnl, 2),
            "pnl_percent": round((price - avg) / avg * 100, 2) if avg > 0 else 0.0,
        })
    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "total_value": round(cash + positions_value, 2),
        "unrealized_pnl": round(unrealized, 2),
        "positions": positions,
    }


def record_snapshot(cache: PriceCache) -> float:
    """Insert one portfolio_snapshots row with the current total value; returns it."""
    with db.connect() as conn:
        total = build_portfolio(conn, cache)["total_value"]
        db.insert_snapshot(conn, total)
    return total
