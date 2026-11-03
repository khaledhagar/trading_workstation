import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App with a fresh SQLite file, the simulator, and the mock LLM."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def no_key_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def pytest_configure(config):
    # Keep tests independent of a developer's .env values.
    os.environ.setdefault("LLM_MOCK", "true")
