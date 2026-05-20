"""OpenAI client wrapper for scraper AI flows."""

from __future__ import annotations

import asyncio
import os

from openai import OpenAI

from scraper.config import AI_MODEL, AI_TIMEOUT_SECONDS


def _get_client() -> OpenAI:
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


async def structured_response(*, prompt: str, text_format: dict, max_output_tokens: int):
    """Run a structured OpenAI Responses API request with timeout."""
    client = _get_client()
    return await asyncio.wait_for(
        asyncio.to_thread(
            client.with_options(timeout=AI_TIMEOUT_SECONDS).responses.create,
            model=AI_MODEL,
            input=prompt,
            text={"format": text_format},
            max_output_tokens=max_output_tokens,
        ),
        timeout=AI_TIMEOUT_SECONDS + 5,
    )
