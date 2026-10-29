"""Chat routes (PLAN.md §8 Chat)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.llm.service import chat_history, handle_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("")
async def post_chat(body: ChatRequest, request: Request) -> dict:
    return await handle_chat(request.app.state, body.message)


@router.get("/history")
def get_chat_history() -> list[dict]:
    return chat_history(limit=50)
