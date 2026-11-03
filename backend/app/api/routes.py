"""All /api routes (PLAN.md §8)."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .. import chat, portfolio
from ..market import price_events

router = APIRouter(prefix="/api")


# --- request models ------------------------------------------------------------

class TickerIn(BaseModel):
    ticker: str


class TradeIn(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    side: Literal["buy", "sell"]

    @field_validator("quantity")
    @classmethod
    def _four_decimals(cls, v: float) -> float:
        if not portfolio.has_valid_precision(v):
            raise ValueError("quantity supports at most 4 decimal places")
        return v


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


# --- system ----------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok"}


# --- market data ---------------------------------------------------------------

@router.get("/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    return StreamingResponse(
        price_events(request.app.state.price_cache, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- watchlist -------------------------------------------------------------------

@router.get("/watchlist")
async def get_watchlist(request: Request):
    return portfolio.watchlist_payload(request.app)


@router.post("/watchlist")
async def add_watchlist(body: TickerIn, request: Request):
    await portfolio.add_to_watchlist(request.app, body.ticker)
    return portfolio.watchlist_payload(request.app)


@router.delete("/watchlist/{ticker}")
async def delete_watchlist(ticker: str, request: Request):
    await portfolio.remove_from_watchlist(request.app, ticker)
    return portfolio.watchlist_payload(request.app)


# --- portfolio -------------------------------------------------------------------

@router.get("/portfolio")
async def get_portfolio(request: Request):
    return portfolio.portfolio_payload(request.app)


@router.post("/portfolio/trade")
async def trade(body: TradeIn, request: Request):
    result = await portfolio.execute_trade(request.app, body.ticker, body.side, body.quantity)
    return {"trade": result, "portfolio": portfolio.portfolio_payload(request.app)}


@router.get("/portfolio/history")
async def get_history():
    return portfolio.history_payload()


# --- chat ------------------------------------------------------------------------

@router.post("/chat")
async def post_chat(body: ChatIn, request: Request):
    return await chat.handle_chat(request.app, body.message.strip())


@router.get("/chat/history")
async def get_chat_history():
    return chat.chat_history()
