"""Paths and environment loading (PLAN.md §5)."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]   # backend/ (or /app in Docker)
PROJECT_ROOT = BACKEND_DIR.parent                     # parent of backend/

# Never overrides variables already set (e.g. by `docker run --env-file`).
load_dotenv(PROJECT_ROOT / ".env", override=False)


def static_dir() -> Path:
    raw = os.environ.get("STATIC_DIR", "").strip()
    return Path(raw) if raw else BACKEND_DIR / "static"


def llm_mock() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() == "true"


def openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()
