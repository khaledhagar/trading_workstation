"""Watchlist changes, trade execution, portfolio valuation and snapshots (PLAN.md §7, §8).

Shared by the REST routes and the chat flow, so manual and LLM actions follow the same rules.
"""

import asyncio
import contextlib
import logging
import sqlite3

from fastapi import FastAPI

from . import db
from .market import MarketDataSource, PriceCache, normalize_ticker

logger = logging.getLogger(__name__)

FULL_EXIT_TOLERANCE = 0.00005
SNAPSHOT_INTERVAL = 30.0
HISTORY_LIMIT = 1000


class TradeError(Exception):
    """A business-rule failure. API → 400 with the message as `detail`."""


class NotWatchedError(Exception):
    """Removing a ticker that isn't in the watchlist. API → 404."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"{ticker} is not in the watchlist")


def _cache(app: FastAPI) -> PriceCache:
    return app.state.price_cache


def _market(app: FastAPI) -> MarketDataSource:
    return app.state.market


def has_valid_precision(quantity: float) -> bool:
    """At most 4 decimal places (PLAN.md §8 Trading Rules)."""
    scaled = quantity * 10_000
    return abs(scaled - round(scaled)) < 1e-6


def validate_quantity(quantity: float) -> float:
    if not (quantity > 0):
        raise TradeError("Quantity must be greater than 0")
    if not has_valid_precision(quantity):
        raise TradeError("Quantity supports at most 4 decimal places")
    return round(quantity, 4)


def _fmt_qty(q: float) -> str:
    return f"{q:.4f}".rstrip("0").rstrip(".")


# --- watchlist ---------------------------------------------------------------

def watchlist_payload(app: FastAPI) -> list[dict]:
    cache = _cache(app)
    with db.connect() as conn:
        tickers = db.watchlist_tickers(conn)
    rows = []
    for t in tickers:
        entry = cache.get(t)
        rows.append(entry.to_dict() if entry else {
            "ticker": t, "price": None, "previous_price": None,
            "timestamp": None, "direction": None, "change_percent": None,
        })
    return rows


async def resync_market(app: FastAPI) -> None:
    """Call after anything that can shrink the tracked set."""
    with db.connect() as conn:
        desired = db.tracked_tickers(conn)
    await _market(app).sync_tickers(desired)


async def add_to_watchlist(app: FastAPI, raw_ticker: str) -> str:
    """Validate, seed the price cache, then persist. Idempotent. Returns the normalized ticker."""
    ticker = normalize_ticker(raw_ticker)
    await _market(app).add_ticker(ticker)      # raises UnknownTickerError / MarketDataUnavailableError
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, ticker) DO NOTHING",
            (db.DEFAULT_USER, ticker, db.now_iso()),
        )
    return ticker


async def remove_from_watchlist(app: FastAPI, raw_ticker: str) -> str:
    ticker = normalize_ticker(raw_ticker)
    with db.connect() as conn:
        deleted = conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (db.DEFAULT_USER, ticker)
        ).rowcount
    if not deleted:
        raise NotWatchedError(ticker)
    await resync_market(app)                    # stays tracked if still held
    return ticker


# --- valuation ---------------------------------------------------------------

def _positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? ORDER BY ticker",
        (db.DEFAULT_USER,),
    ).fetchall()


def _cash(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id = ?", (db.DEFAULT_USER,)
    ).fetchone()
    return float(row[0]) if row else 0.0


def _total_value(conn: sqlite3.Connection, cache: PriceCache) -> float:
    total = _cash(conn)
    for p in _positions(conn):
        price = cache.get_price(p["ticker"]) or p["avg_cost"]
        total += p["quantity"] * price
    return round(total, 2)


def portfolio_from_conn(conn: sqlite3.Connection, cache: PriceCache) -> dict:
    cash = _cash(conn)
    positions = []
    positions_value = 0.0
    total_cost = 0.0
    for p in _positions(conn):
        qty, avg = p["quantity"], p["avg_cost"]
        price = cache.get_price(p["ticker"]) or avg
        market_value = qty * price
        cost = qty * avg
        pnl = market_value - cost
        positions_value += market_value
        total_cost += cost
        positions.append({
            "ticker": p["ticker"],
            "quantity": round(qty, 4),
            "avg_cost": round(avg, 2),
            "current_price": round(price, 2),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(pnl, 2),
            "pnl_percent": round(pnl / cost * 100, 2) if cost > 0 else 0.0,
        })
    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "total_value": round(cash + positions_value, 2),
        "unrealized_pnl": round(positions_value - total_cost, 2),
        "positions": positions,
    }


def portfolio_payload(app: FastAPI) -> dict:
    with db.connect() as conn:
        return portfolio_from_conn(conn, _cache(app))


def _insert_snapshot(conn: sqlite3.Connection, cache: PriceCache) -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
        (db.new_id(), db.DEFAULT_USER, _total_value(conn, cache), db.now_iso()),
    )


def record_snapshot(app: FastAPI) -> None:
    with db.connect() as conn:
        _insert_snapshot(conn, _cache(app))


def history_payload() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT total_value, recorded_at FROM ("
            "  SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? "
            "  ORDER BY recorded_at DESC LIMIT ?"
            ") ORDER BY recorded_at ASC",
            (db.DEFAULT_USER, HISTORY_LIMIT),
        ).fetchall()
    return [{"total_value": round(r[0], 2), "recorded_at": r[1]} for r in rows]


async def snapshot_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL)
        try:
            record_snapshot(app)
        except Exception:
            logger.exception("Portfolio snapshot failed")


def start_snapshot_task(app: FastAPI) -> asyncio.Task:
    return asyncio.create_task(snapshot_loop(app), name="portfolio-snapshots")


async def stop_task(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# --- trades ------------------------------------------------------------------

async def execute_trade(app: FastAPI, raw_ticker: str, side: str, quantity: float) -> dict:
    """Run one market order atomically. Returns the trade record. Raises TradeError and market errors."""
    ticker = normalize_ticker(raw_ticker)
    if side not in ("buy", "sell"):
        raise TradeError("Side must be 'buy' or 'sell'")
    quantity = validate_quantity(quantity)

    if side == "buy":
        with db.connect() as conn:
            watched = db.is_watched(conn, ticker)
        if not watched:
            await add_to_watchlist(app, ticker)   # same validation and cache seeding (PLAN.md §8)

    cache = _cache(app)
    position_closed = False
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            price = cache.get_price(ticker)
            if price is None:
                raise TradeError(f"No price available for {ticker} yet")

            cash = _cash(conn)
            row = conn.execute(
                "SELECT quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
                (db.DEFAULT_USER, ticker),
            ).fetchone()
            held = row["quantity"] if row else 0.0
            now = db.now_iso()

            if side == "buy":
                cost = quantity * price
                if cash + 1e-9 < cost:
                    raise TradeError(f"Insufficient cash: need ${cost:,.2f}, have ${cash:,.2f}")
                new_qty = round(held + quantity, 4)
                new_avg = (held * row["avg_cost"] + quantity * price) / new_qty if row else price
                new_cash = round(cash - cost, 2)
                conn.execute(
                    "INSERT INTO positions (user_id, ticker, quantity, avg_cost, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, ticker) DO UPDATE SET "
                    "quantity = excluded.quantity, avg_cost = excluded.avg_cost, "
                    "updated_at = excluded.updated_at",
                    (db.DEFAULT_USER, ticker, new_qty, new_avg, now),
                )
            else:
                if held + 1e-9 < quantity:
                    raise TradeError(
                        f"Insufficient shares: have {_fmt_qty(held)}, tried to sell {_fmt_qty(quantity)}"
                    )
                remaining = round(held - quantity, 4)
                new_cash = round(cash + quantity * price, 2)
                if remaining < FULL_EXIT_TOLERANCE:
                    conn.execute(
                        "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
                        (db.DEFAULT_USER, ticker),
                    )
                    position_closed = True
                else:
                    conn.execute(
                        "UPDATE positions SET quantity = ?, updated_at = ? WHERE user_id = ? AND ticker = ?",
                        (remaining, now, db.DEFAULT_USER, ticker),
                    )

            conn.execute(
                "UPDATE users_profile SET cash_balance = ? WHERE id = ?", (new_cash, db.DEFAULT_USER)
            )
            trade = {
                "id": db.new_id(),
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
                "executed_at": now,
            }
            conn.execute(
                "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (trade["id"], db.DEFAULT_USER, ticker, side, quantity, price, now),
            )
            _insert_snapshot(conn, cache)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    if position_closed:
        await resync_market(app)   # untracks it if not watched
    return trade
