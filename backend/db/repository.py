"""Repository functions over the SQLite schema (TEAM_CONTRACTS.md §2, PLAN.md §8 Trading Rules)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from .connection import DEFAULT_USER, iso_ms, utc_now_iso, utc_now_iso_ms

FULL_EXIT_TOLERANCE = 0.00005
_EPS = 1e-9


class TradeError(ValueError):
    """Business-rule failure of a trade; str(exc) is the exact 400 `detail`."""


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_qty(value: float) -> str:
    text = f"{round(value, 4):.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


# ---------------------------------------------------------------- tracked set / profile / positions


def tracked_tickers(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> set[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? "
        "UNION SELECT ticker FROM positions WHERE user_id = ?",
        (user_id, user_id),
    ).fetchall()
    return {r["ticker"] for r in rows}


def get_cash(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> float:
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)
    ).fetchone()
    return float(row["cash_balance"]) if row else 0.0


def _position_dict(row: sqlite3.Row) -> dict:
    return {
        "ticker": row["ticker"],
        "quantity": row["quantity"],
        "avg_cost": row["avg_cost"],
        "updated_at": row["updated_at"],
    }


def list_positions(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> list[dict]:
    rows = conn.execute(
        "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
        "WHERE user_id = ? ORDER BY ticker",
        (user_id,),
    ).fetchall()
    return [_position_dict(r) for r in rows]


def get_position(
    conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER
) -> dict | None:
    row = conn.execute(
        "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
        "WHERE user_id = ? AND ticker = ?",
        (user_id, ticker.strip().upper()),
    ).fetchone()
    return _position_dict(row) if row else None


# ---------------------------------------------------------------- watchlist


def list_watchlist(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, ticker",
        (user_id,),
    ).fetchall()
    return [r["ticker"] for r in rows]


def _next_added_at(conn: sqlite3.Connection, user_id: str) -> str:
    """Now (ms precision), bumped past the latest existing added_at so the order is insertion order."""
    now = utc_now_iso_ms()
    row = conn.execute(
        "SELECT MAX(added_at) AS m FROM watchlist WHERE user_id = ?", (user_id,)
    ).fetchone()
    latest = row["m"] if row else None
    if latest and latest >= now:
        try:
            dt = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            return iso_ms(dt + timedelta(milliseconds=1))
        except ValueError:
            return now
    return now


def add_watchlist(conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER) -> bool:
    cur = conn.execute(
        "INSERT INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, ticker) DO NOTHING",
        (user_id, ticker.strip().upper(), _next_added_at(conn, user_id)),
    )
    return cur.rowcount == 1


def remove_watchlist(
    conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER
) -> bool:
    cur = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (user_id, ticker.strip().upper()),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------- trades


def execute_trade(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    side: str,
    quantity: float,
    get_price: Callable[[str], float | None],
    user_id: str = DEFAULT_USER,
) -> dict:
    """Execute a market order atomically (one BEGIN IMMEDIATE transaction).

    Raises TradeError (exact PLAN.md §8 messages) on business-rule failures; the DB is unchanged.
    """
    ticker = ticker.strip().upper()
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    qty = round(float(quantity), 4)
    if qty <= 0:
        raise ValueError("quantity must be > 0")

    conn.execute("BEGIN IMMEDIATE")
    try:
        price = get_price(ticker)
        if price is None:
            raise TradeError(f"No price available for {ticker} yet")
        price = float(price)

        cash = get_cash(conn, user_id)
        pos = get_position(conn, ticker, user_id)
        held = pos["quantity"] if pos else 0.0
        now = utc_now_iso()

        if side == "buy":
            cost = qty * price
            if cost > cash + _EPS:
                raise TradeError(
                    f"Insufficient cash: need {_fmt_money(cost)}, have {_fmt_money(cash)}"
                )
            new_cash = max(round(cash - cost, 2), 0.0)
            new_qty = round(held + qty, 4)
            new_avg = (held * pos["avg_cost"] + qty * price) / new_qty if pos else price
            conn.execute(
                "INSERT INTO positions (user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, ticker) DO UPDATE SET "
                "quantity = excluded.quantity, avg_cost = excluded.avg_cost, "
                "updated_at = excluded.updated_at",
                (user_id, ticker, new_qty, new_avg, now),
            )
        else:
            if held + _EPS < qty:
                raise TradeError(
                    f"Insufficient shares: have {_fmt_qty(held)}, tried to sell {_fmt_qty(qty)}"
                )
            new_cash = round(cash + qty * price, 2)
            remaining = round(held - qty, 4)
            if remaining < FULL_EXIT_TOLERANCE:
                conn.execute(
                    "DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker)
                )
            else:
                conn.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? "
                    "WHERE user_id = ? AND ticker = ?",
                    (remaining, now, user_id, ticker),
                )

        conn.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?", (new_cash, user_id)
        )
        trade = {
            "id": str(uuid.uuid4()),
            "ticker": ticker,
            "side": side,
            "quantity": qty,
            "price": round(price, 2),
            "executed_at": now,
        }
        conn.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade["id"], user_id, ticker, side, qty, price, now),
        )

        total = new_cash
        for p in list_positions(conn, user_id):
            p_price = price if p["ticker"] == ticker else get_price(p["ticker"])
            total += p["quantity"] * (float(p_price) if p_price is not None else p["avg_cost"])
        insert_snapshot(conn, total, user_id)

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return trade


# ---------------------------------------------------------------- snapshots


def insert_snapshot(
    conn: sqlite3.Connection, total_value: float, user_id: str = DEFAULT_USER
) -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, round(float(total_value), 2), utc_now_iso()),
    )


def list_snapshots(
    conn: sqlite3.Connection, limit: int = 1000, user_id: str = DEFAULT_USER
) -> list[dict]:
    rows = conn.execute(
        "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? "
        "ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
        (user_id, int(limit)),
    ).fetchall()
    return [{"total_value": r["total_value"], "recorded_at": r["recorded_at"]} for r in reversed(rows)]


# ---------------------------------------------------------------- chat


def _chat_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "actions": json.loads(row["actions"]) if row["actions"] is not None else None,
        "created_at": row["created_at"],
    }


def insert_chat_message(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    actions: dict | None,
    user_id: str = DEFAULT_USER,
) -> dict:
    if role not in ("user", "assistant"):
        raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
    msg = {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": utc_now_iso(),
    }
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            msg["id"],
            user_id,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            msg["created_at"],
        ),
    )
    return msg


def list_chat_messages(
    conn: sqlite3.Connection, limit: int = 50, user_id: str = DEFAULT_USER
) -> list[dict]:
    rows = conn.execute(
        "SELECT id, role, content, actions, created_at FROM chat_messages WHERE user_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (user_id, int(limit)),
    ).fetchall()
    return [_chat_dict(r) for r in reversed(rows)]
