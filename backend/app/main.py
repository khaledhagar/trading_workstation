"""FastAPI app: lifespan (DB → market data → snapshots), error mapping, routes, static frontend."""

import asyncio
import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, portfolio
from .api.routes import router
from .market import (
    InvalidTickerError,
    MarketDataUnavailableError,
    PriceCache,
    UnknownTickerError,
    create_market_data_source,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if config.llm_mock():
        logger.info("LLM_MOCK=true: chat uses deterministic mock responses")
    elif not config.openrouter_key():
        logger.warning("OPENROUTER_API_KEY is not set: chat will reply with a configuration notice")
    else:
        # litellm takes seconds to import; warm it up off the event loop so the first chat is fast.
        asyncio.get_running_loop().run_in_executor(None, importlib.import_module, "litellm")
    cache = PriceCache()
    market = create_market_data_source(cache)
    with db.connect() as conn:
        await market.start(db.tracked_tickers(conn))
    app.state.price_cache = cache
    app.state.market = market
    portfolio.record_snapshot(app)                      # startup snapshot (PLAN.md §7)
    snapshot_task = portfolio.start_snapshot_task(app)
    try:
        yield
    finally:
        await portfolio.stop_task(snapshot_task)
        await market.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="trading_workstation", lifespan=lifespan)

    @app.exception_handler(InvalidTickerError)
    async def _invalid(_: Request, exc: InvalidTickerError):
        return JSONResponse(status_code=400, content={"detail": "Invalid ticker"})

    @app.exception_handler(UnknownTickerError)
    async def _unknown(_: Request, exc: UnknownTickerError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(MarketDataUnavailableError)
    async def _unavailable(_: Request, exc: MarketDataUnavailableError):
        logger.warning("Market data unavailable: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Market data unavailable, try again shortly"})

    @app.exception_handler(portfolio.TradeError)
    async def _trade(_: Request, exc: portfolio.TradeError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(portfolio.NotWatchedError)
    async def _not_watched(_: Request, exc: portfolio.NotWatchedError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    app.include_router(router)

    static = config.static_dir()
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    else:
        logger.info("No frontend build at %s; serving the API only", static)
    return app


app = create_app()
