"""AI extraction helpers for pipeline stages."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
from openai import APITimeoutError

from scraper.ai.client import structured_response
from scraper.ai.parsers import parse_json_output, response_refusal
from scraper.ai.prompts import build_extract_jobs_prompt, build_network_fallback_prompt
from scraper.config import AI_TIMEOUT_SECONDS
from scraper.schemas import JOB_LISTINGS_RESPONSE_FORMAT, SCRAPER_SPEC_RESPONSE_FORMAT


def empty_job_result(source_url: str, page_title: str | None, notes: str) -> dict:
    return {
        "source_url": source_url,
        "page_title": page_title,
        "company_name": None,
        "jobs": [],
        "notes": notes,
    }


def default_scraper_spec(explanation: str) -> dict:
    return {
        "requires_browser": True,
        "api_target_url": None,
        "browser_target_url": None,
        "data_delivery_type": "unknown",
        "method": "NONE",
        "required_headers": {
            "accept": None,
            "content_type": None,
            "authorization": None,
            "user_agent": None,
            "referer": None,
        },
        "payload": None,
        "json_path_to_listings": None,
        "explanation": explanation,
    }


async def extract_jobs_from_page_data(data: dict) -> dict:
    prompt = build_extract_jobs_prompt(data)
    try:
        response = await structured_response(
            prompt=prompt,
            text_format=JOB_LISTINGS_RESPONSE_FORMAT,
            max_output_tokens=6000,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"AI extraction exceeded {AI_TIMEOUT_SECONDS:.0f} seconds")
    except (APITimeoutError, TimeoutError):
        raise HTTPException(status_code=504, detail=f"OpenAI request exceeded {AI_TIMEOUT_SECONDS:.0f} seconds")

    if getattr(response, "status", None) == "incomplete":
        incomplete_details = getattr(response, "incomplete_details", None)
        reason = getattr(incomplete_details, "reason", None) or "unknown"
        return empty_job_result(data["final_url"], data.get("title"), f"AI response was incomplete: {reason}")

    refusal = response_refusal(response)
    if refusal:
        return empty_job_result(data["final_url"], data.get("title"), refusal)

    raw = response.output_text
    fallback = empty_job_result(
        data["final_url"],
        data.get("title"),
        f"AI did not return valid JSON. Raw prefix: {raw[:1000]}",
    )
    return parse_json_output(raw, fallback)


async def build_fallback_spec_from_logs(source_url: str, traffic_logs: list[dict]) -> dict:
    prompt = build_network_fallback_prompt(traffic_logs)
    response = await structured_response(
        prompt=prompt,
        text_format=SCRAPER_SPEC_RESPONSE_FORMAT,
        max_output_tokens=3000,
    )

    refusal = response_refusal(response)
    if refusal:
        raise HTTPException(status_code=422, detail=f"AI Refusal mapping request footprint: {refusal}")

    return parse_json_output(response.output_text, default_scraper_spec("AI returned invalid JSON for fallback spec."))
