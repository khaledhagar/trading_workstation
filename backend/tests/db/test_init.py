import re
import sqlite3
from pathlib import Path

import db
from db import connection


def test_get_db_path_default(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    p = db.get_db_path()
    assert p.name == "trading_workstation.db"
    assert p.parent.name == "db"
    # project root = parent of backend/
    assert (p.parent.parent / "backend" / "db" / "connection.py").exists()


def test_get_db_path_empty_env_uses_default(monkeypatch):
    monkeypatch.setenv("DB_PATH", "  ")
    assert db.get_db_path() == connection.DEFAULT_DB_PATH


def test_get_db_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    assert db.get_db_path() == tmp_path / "x.db"


def test_init_db_uses_env_and_creates_parent(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "deeper" / "app.db"
    monkeypatch.setenv("DB_PATH", str(target))
    assert db.init_db() == target
    assert target.exists()


def test_tables_and_wal(db_path):
    with db.connect(db_path) as c:
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = c.execute("PRAGMA busy_timeout").fetchone()[0]
    assert {"users_profile", "watchlist", "positions", "trades",
            "portfolio_snapshots", "chat_messages"} <= names
    assert mode.lower() == "wal"
    assert timeout == 5000


def test_seed(conn):
    assert db.get_cash(conn) == 10000.0
    assert db.list_watchlist(conn) == list(db.DEFAULT_TICKERS)
    assert db.list_watchlist(conn) == ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
                                       "NVDA", "META", "JPM", "V", "NFLX"]
    assert db.list_positions(conn) == []
    row = conn.execute("SELECT created_at FROM users_profile WHERE id='default'").fetchone()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["created_at"])


def test_init_idempotent(db_path):
    db.init_db(db_path)
    db.init_db(db_path)
    with db.connect(db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 10


def test_seed_not_reapplied_after_watchlist_emptied(db_path):
    with db.connect(db_path) as c:
        for t in db.list_watchlist(c):
            db.remove_watchlist(c, t)
        c.execute("UPDATE users_profile SET cash_balance = 42.0")
    db.init_db(db_path)
    with db.connect(db_path) as c:
        assert db.list_watchlist(c) == []
        assert db.get_cash(c) == 42.0


def test_reseed_after_file_deleted(tmp_path):
    p = db.init_db(tmp_path / "r.db")
    with db.connect(p) as c:
        db.remove_watchlist(c, "AAPL")
    for f in tmp_path.glob("r.db*"):
        f.unlink()
    db.init_db(p)
    with db.connect(p) as c:
        assert "AAPL" in db.list_watchlist(c)


def test_connect_settings(db_path):
    with db.connect(db_path) as c:
        assert c.row_factory is sqlite3.Row
        assert c.isolation_level is None


def test_connect_context_manager_closes(db_path):
    with db.connect(db_path) as c:
        pass
    try:
        c.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        pass
    else:  # pragma: no cover
        raise AssertionError("connection should be closed")


def test_connect_accepts_str_path(db_path):
    with db.connect(str(db_path)) as c:
        assert db.get_cash(c) == 10000.0


def test_utc_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", db.utc_now_iso())
