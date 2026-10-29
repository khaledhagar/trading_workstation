"""FastAPI app: lifespan wiring, error handlers, API routers, then the static frontend.

Run locally: cd backend && uv run uvicorn app.main:app --port 8000
"""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import db
from app.api import chat, health, portfolio, stream, watchlist
from app.market import (
    InvalidTickerError,
    MarketDataUnavailableError,
    PriceCache,
    UnknownTickerError,
    create_market_data_source,
)
from app.services.portfolio import record_snapshot
from app.services.watchlist import NotInWatchlistError

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
SNAPSHOT_INTERVAL = 30.0
UNAVAILABLE_DETAIL = "Market data unavailable, try again shortly"
NO_LLM_KEY_WARNING = "OPENROUTER_API_KEY is not set and LLM_MOCK is not true: chat is disabled"


def _configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("db").setLevel(logging.INFO)


def _warn_if_llm_unconfigured() -> None:
    mock = os.environ.get("LLM_MOCK", "").strip().lower() == "true"
    if not mock and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        logger.warning(NO_LLM_KEY_WARNING)


def _safe_snapshot(cache: PriceCache) -> None:
    try:
        record_snapshot(cache)
    except Exception:
        logger.exception("Portfolio snapshot failed")


async def _snapshot_loop(cache: PriceCache, interval: float) -> None:
    """Record a portfolio snapshot every `interval` seconds; errors are logged, never fatal."""
    while True:
        await asyncio.sleep(interval)
        _safe_snapshot(cache)


def _make_lifespan(snapshot_interval: float):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _configure_logging()
        _warn_if_llm_unconfigured()
        db_path = db.init_db()
        logger.info("Database: %s", db_path)

        cache = PriceCache()
        market = create_market_data_source(cache)
        with db.connect() as conn:
            tickers = db.tracked_tickers(conn)
        await market.start(tickers)
        app.state.price_cache = cache
        app.state.market = market

        _safe_snapshot(cache)                   # one at startup (PLAN.md §7)
        task = asyncio.create_task(_snapshot_loop(cache, snapshot_interval),
                                   name="portfolio-snapshots")
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await market.stop()

    return lifespan


def _register_error_handlers(app: FastAPI) -> None:
    async def bad_request(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    async def not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    async def unavailable(_: Request, exc: Exception) -> JSONResponse:
        logger.warning("Market data unavailable: %r", exc)
        return JSONResponse(status_code=503, content={"detail": UNAVAILABLE_DETAIL})

    for exc_type in (InvalidTickerError, UnknownTickerError, db.TradeError):
        app.add_exception_handler(exc_type, bad_request)
    app.add_exception_handler(NotInWatchlistError, not_found)
    app.add_exception_handler(MarketDataUnavailableError, unavailable)


def _include_routers(app: FastAPI) -> None:
    for module in (stream, portfolio, watchlist, chat, health):
        app.include_router(module.router)


def _static_dir() -> Path:
    raw = os.environ.get("STATIC_DIR", "").strip()
    return Path(raw) if raw else BACKEND_DIR / "static"


def create_app(*, load_env: bool = True, snapshot_interval: float = SNAPSHOT_INTERVAL,
               static_dir: Path | None = None) -> FastAPI:
    """App factory. Tests pass load_env=False so a developer .env file never leaks in."""
    if load_env:
        load_dotenv(PROJECT_ROOT / ".env", override=False)

    app = FastAPI(title="trading_workstation", lifespan=_make_lifespan(snapshot_interval))
    _register_error_handlers(app)
    _include_routers(app)

    # Mounted last so every /api route takes precedence (PLAN.md §11).
    static = static_dir or _static_dir()
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
        logger.info("Serving frontend from %s", static)
    else:
        logger.warning("No frontend build at %s; serving the API only", static)
    return app


app = create_app()
