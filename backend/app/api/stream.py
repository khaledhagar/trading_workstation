from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.market import price_events

router = APIRouter(prefix="/api/stream", tags=["market"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    """SSE: one unnamed event every 500 ms with every tracked ticker (PLAN.md §6)."""
    return StreamingResponse(
        price_events(request.app.state.price_cache, request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
