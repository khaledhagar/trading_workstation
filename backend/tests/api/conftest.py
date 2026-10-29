"""App fixtures: a fresh temp SQLite DB, the simulator source, mock LLM, no static mount."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "no-static"))
    return tmp_path


@pytest.fixture
def app(app_env):
    return create_app(load_env=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:                  # runs the lifespan
        yield c
