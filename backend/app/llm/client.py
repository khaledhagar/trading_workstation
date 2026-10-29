"""Real LLM call: LiteLLM → OpenRouter → gpt-oss-120b on Cerebras (cerebras-inference skill)."""

import os

import litellm

from .models import LLMResponse

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
TIMEOUT_SECONDS = 30


def mock_enabled() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() == "true"


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


async def complete(messages: list[dict]) -> str:
    """Return the model's raw structured-output text. Raises on any provider/network error."""
    response = await litellm.acompletion(
        model=MODEL,
        messages=messages,
        response_format=LLMResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,  # PLAN.md §9: no retries, the user can resend
        api_key=api_key(),
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM returned empty content")
    return content
