from fastapi import APIRouter, Request
from pydantic import BaseModel

import db
from app.services import add_ticker, remove_ticker, watchlist_rows

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTickerRequest(BaseModel):
    ticker: str


@router.get("")
async def get_watchlist(request: Request) -> list[dict]:
    with db.connect() as conn:
        return watchlist_rows(conn, request.app.state.price_cache)


@router.post("")
async def post_watchlist(body: AddTickerRequest, request: Request) -> list[dict]:
    return await add_ticker(request.app.state, body.ticker)


@router.delete("/{ticker}")
async def delete_watchlist(ticker: str, request: Request) -> list[dict]:
    return await remove_ticker(request.app.state, ticker)
