"""OpenAI client wrapper for scraper AI flows."""

from __future__ import annotations

import asyncio
import os

from openai import OpenAI

from scraper.config import AI_MODEL, AI_TIMEOUT_SECONDS, DISCOVERY_CLASSIFIER_MODEL, DISCOVERY_OPENAI_MODEL


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


async def web_search_structured_response(*, prompt: str, text_format: dict, max_output_tokens: int):
    """Run a structured Responses request with hosted web search enabled."""
    client = _get_client()
    return await asyncio.wait_for(
        asyncio.to_thread(
            client.with_options(timeout=AI_TIMEOUT_SECONDS).responses.create,
            model=DISCOVERY_OPENAI_MODEL,
            input=prompt,
            tools=[{"type": "web_search", "search_context_size": "low"}],
            text={"format": text_format},
            max_output_tokens=max_output_tokens,
        ),
        timeout=AI_TIMEOUT_SECONDS + 5,
    )


async def discovery_classifier_structured_response(*, prompt: str, text_format: dict, max_output_tokens: int):
    """Run the fast discovery classifier without hosted web search."""
    client = _get_client()
    return await asyncio.wait_for(
        asyncio.to_thread(
            client.with_options(timeout=AI_TIMEOUT_SECONDS).responses.create,
            model=DISCOVERY_CLASSIFIER_MODEL,
            input=prompt,
            text={"format": text_format},
            max_output_tokens=max_output_tokens,
        ),
        timeout=AI_TIMEOUT_SECONDS + 5,
    )
