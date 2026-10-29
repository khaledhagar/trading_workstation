"""Structured output schema the LLM must return (PLAN.md §9).

Every field is required (strict structured-output modes need that), and `side`/`action`
are Literals so they become enums in the JSON schema.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class TradeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: Literal["add", "remove"]


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    trades: list[TradeAction]
    watchlist_changes: list[WatchlistChange]
