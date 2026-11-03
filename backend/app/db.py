"""SQLite access: path resolution, schema, seed data and small query helpers (PLAN.md §7)."""

import logging
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_USER = "default"
DEFAULT_CASH = 10000.0
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users_profile (
    id TEXT PRIMARY KEY DEFAULT 'default',
    cash_balance REAL NOT NULL DEFAULT 10000.0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (user_id, ticker)
);
CREATE TABLE IF NOT EXISTS positions (
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, ticker)
);
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    total_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_time ON portfolio_snapshots (user_id, recorded_at);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    actions TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_user_time ON chat_messages (user_id, created_at);
"""


def db_path() -> Path:
    raw = os.environ.get("DB_PATH", "").strip()
    return Path(raw) if raw else PROJECT_ROOT / "db" / "trading_workstation.db"


def now_iso() -> str:
    """ISO 8601 UTC with milliseconds, so rows inserted in the same second still sort correctly."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Short-lived connection in autocommit mode; use BEGIN IMMEDIATE for multi-statement writes."""
    conn = sqlite3.connect(db_path(), isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create the file, enable WAL, create tables, seed defaults if the default user is missing."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        exists = conn.execute(
            "SELECT 1 FROM users_profile WHERE id = ?", (DEFAULT_USER,)
        ).fetchone()
        if exists is None:
            now = now_iso()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                (DEFAULT_USER, DEFAULT_CASH, now),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?)",
                [(DEFAULT_USER, t, now) for t in DEFAULT_WATCHLIST],
            )
            conn.execute("COMMIT")
            logger.info("Seeded default user and watchlist")
    logger.info("Database ready at %s", path)


def tracked_tickers(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> set[str]:
    """PLAN.md §6 Tracked Tickers: watchlist ∪ tickers with an open position."""
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? "
        "UNION SELECT ticker FROM positions WHERE user_id = ?",
        (user_id, user_id),
    ).fetchall()
    return {row[0] for row in rows}


def watchlist_tickers(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid", (user_id,)
    ).fetchall()
    return [r[0] for r in rows]


def is_watched(conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER) -> bool:
    return conn.execute(
        "SELECT 1 FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker)
    ).fetchone() is not None
