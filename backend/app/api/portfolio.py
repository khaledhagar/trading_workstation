from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

import db
from app.services import build_portfolio, trade

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

HISTORY_LIMIT = 1000


def has_max_4_decimals(value: float) -> bool:
    return Decimal(str(value)).as_tuple().exponent >= -4


class TradeRequest(BaseModel):
    ticker: str
    quantity: float = Field(gt=0, allow_inf_nan=False)
    side: Literal["buy", "sell"]

    @field_validator("quantity")
    @classmethod
    def _max_4_decimals(cls, value: float) -> float:
        if not has_max_4_decimals(value):
            raise ValueError("quantity may have at most 4 decimal places")
        return value


@router.get("")
async def get_portfolio(request: Request) -> dict:
    with db.connect() as conn:
        return build_portfolio(conn, request.app.state.price_cache)


@router.post("/trade")
async def post_trade(body: TradeRequest, request: Request) -> dict:
    return await trade(request.app.state, body.ticker, body.side, body.quantity)


@router.get("/history")
async def get_history() -> list[dict]:
    with db.connect() as conn:
        return db.list_snapshots(conn, limit=HISTORY_LIMIT)
