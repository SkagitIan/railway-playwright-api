"""Stage 2: acquire raw data for downstream extraction."""

import asyncio
import json
import os
import tempfile
import time
import urllib.request

from scraper.ats.api_targets import build_api_target
from scraper.browser.har import parse_har_entries
from scraper.config import BROWSER_MAX_CONCURRENCY, SPEC_CACHE_TTL_SECONDS
from scraper.page_data import get_page_data_and_har

_BROWSER_SEMAPHORE = asyncio.Semaphore(BROWSER_MAX_CONCURRENCY)
_SPEC_CACHE: dict[str, tuple[float, dict]] = {}


def _has_acquired_data(raw_data: dict) -> bool:
    return bool(
        raw_data.get("text")
        or raw_data.get("container_html")
        or raw_data.get("links")
        or raw_data.get("json_body")
    )


def _is_cf_challenge(raw_data: dict) -> bool:
    """Return True if the acquired page is a Cloudflare bot-challenge page."""
    title = (raw_data.get("title") or "").lower().strip(".")
    return title in {"just a moment", "please wait", "checking your browser"}


def _is_empty_js_app_shell(raw_data: dict) -> bool:
    text = (raw_data.get("text") or "").strip()
    links = raw_data.get("links") or []
    json_body = raw_data.get("json_body")
    if text or links or json_body:
        return False
    for entry in raw_data.get("har_entries") or []:
        snippet = (entry.get("response_body_snippet") or "").lower()
        if "<div id=\"root\"></div>" in snippet or "<div id='root'></div>" in snippet:
            return True
    return False


async def run(stage_input: dict) -> dict:
    """Normalize raw acquisition output shape.

    This is intentionally simple while the pipeline modules are being split out.
    """
    classification = stage_input["classification"]
    domain = stage_input.get("domain", "")
    now = time.time()
    strategy = classification.get("strategy", "BROWSER_RENDER")
    spec = classification.get("spec") or {}
    cache_key = spec.get("browser_target_url") if strategy == "PROMOTED_SPEC" and spec.get("browser_target_url") else domain
    cached = _SPEC_CACHE.get(cache_key)
    if cached and (now - cached[0]) < SPEC_CACHE_TTL_SECONDS and not _is_cf_challenge(cached[1]):
        return {**stage_input, "raw_data": cached[1], "acquisition_strategy": "spec_cache_ttl", "fallback_reason": stage_input.get("fallback_reason", "none")}

    fallback_reason = stage_input.get("fallback_reason", "none")
    if strategy == "DIRECT_JSON_API":
        acquisition_strategy = "ats_deterministic"
    elif strategy == "PROMOTED_SPEC":
        acquisition_strategy = "promoted_spec_replay"
    elif strategy == "BROWSER_HAR":
        acquisition_strategy = "har_analysis_and_ai_spec"
    else:
        acquisition_strategy = "browser_render_and_extract"

    if strategy == "DIRECT_JSON_API":
        raw_data = await _acquire_direct_json(stage_input)
    elif strategy == "PROMOTED_SPEC":
        spec = classification.get("spec") or {}
        if spec.get("api_target_url") and spec.get("method") != "NONE":
            raw_data = await _acquire_promoted_spec(stage_input)
        elif spec.get("browser_target_url"):
            async with _BROWSER_SEMAPHORE:
                raw_data = await _acquire_browser_har(
                    {**stage_input, "acquisition_url": spec["browser_target_url"]},
                    fallback_reason,
                )
        else:
            raw_data = await _acquire_promoted_spec(stage_input)
    else:
        async with _BROWSER_SEMAPHORE:
            raw_data = await _acquire_browser_har(stage_input, fallback_reason)

    if _has_acquired_data(raw_data) and not _is_cf_challenge(raw_data) and not _is_empty_js_app_shell(raw_data):
        _SPEC_CACHE[cache_key] = (now, raw_data)
    return {**stage_input, "raw_data": raw_data, "acquisition_strategy": acquisition_strategy}


async def _fetch_json(url: str, *, method: str = "GET", headers: dict | None = None, payload: str | None = None):
    def _request():
        data = payload.encode("utf-8") if payload and method.upper() != "GET" else None
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=method.upper())
        with urllib.request.urlopen(request, timeout=60) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))

    return await asyncio.to_thread(_request)


def _with_ultipro_pagination_payload(payload: str | None, *, skip: int, top: int) -> str | None:
    if not payload:
        return payload
    data = json.loads(payload)
    opportunity_search = data.setdefault("opportunitySearch", {})
    opportunity_search["Skip"] = skip
    opportunity_search["Top"] = top
    return json.dumps(data)


async def _fetch_paginated_json(target: dict) -> dict:
    pagination = target.get("pagination") or {}
    if pagination.get("type") != "ultipro_skip_top":
        return await _fetch_json(
            target["api_target_url"],
            method=target.get("method", "GET"),
            headers=target.get("headers"),
            payload=target.get("payload"),
        )

    page_size = int(pagination.get("page_size") or 100)
    max_pages = int(pagination.get("max_pages") or 10)
    all_opportunities = []
    result: dict = {}
    for page_num in range(max_pages):
        skip = page_num * page_size
        payload = _with_ultipro_pagination_payload(target.get("payload"), skip=skip, top=page_size)
        page = await _fetch_json(
            target["api_target_url"],
            method=target.get("method", "POST"),
            headers=target.get("headers"),
            payload=payload,
        )
        if not isinstance(page, dict):
            break
        if not result:
            result = dict(page)
        opportunities = page.get("opportunities") or []
        all_opportunities.extend(opportunities)
        total_count = page.get("totalCount")
        if not opportunities or (isinstance(total_count, int) and len(all_opportunities) >= total_count):
            break

    result["opportunities"] = all_opportunities
    return result


async def _acquire_direct_json(stage_input: dict) -> dict:
    classification = stage_input["classification"]
    target = build_api_target(stage_input["url"], classification.get("ats"))
    json_body = None
    api_target_url = None
    if target:
        api_target_url = target["api_target_url"]
        json_body = await _fetch_paginated_json(target)

    return {
        "source_url": stage_input["url"],
        "final_url": api_target_url or stage_input["url"],
        "title": None,
        "data_type": "json",
        "text": None,
        "container_html": None,
        "links": [],
        "json_body": json_body,
        "har_entries": [],
        "pages_scraped": 0,
        "fallback_reason": stage_input.get("fallback_reason", "none"),
        "api_target_url": api_target_url,
    }


async def _acquire_promoted_spec(stage_input: dict) -> dict:
    spec = stage_input.get("classification", {}).get("spec") or {}
    api_target_url = spec.get("api_target_url")
    method = spec.get("method") or "GET"
    headers = {k.replace("_", "-"): v for k, v in (spec.get("required_headers") or {}).items() if v}
    json_body = None
    if api_target_url and method != "NONE":
        json_body = await _fetch_json(api_target_url, method=method, headers=headers, payload=spec.get("payload"))

    return {
        "source_url": stage_input["url"],
        "final_url": api_target_url or spec.get("browser_target_url") or stage_input["url"],
        "title": None,
        "data_type": "json" if json_body is not None else "unknown",
        "text": None,
        "container_html": None,
        "links": [],
        "json_body": json_body,
        "har_entries": [],
        "pages_scraped": 0,
        "fallback_reason": stage_input.get("fallback_reason", "none"),
        "api_target_url": api_target_url,
    }


async def _acquire_browser_har(stage_input: dict, fallback_reason: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".har", delete=False) as tmp:
        har_path = tmp.name

    try:
        acquisition_url = stage_input.get("acquisition_url") or stage_input["url"]
        page_data = await get_page_data_and_har(acquisition_url, har_path)
        har_entries = parse_har_entries(har_path)
        return {
            "requested_url": stage_input["url"],
            "source_url": acquisition_url,
            "final_url": page_data.get("final_url"),
            "title": page_data.get("title"),
            "data_type": "html",
            "text": page_data.get("text"),
            "container_html": None,
            "links": page_data.get("links", []),
            "json_body": None,
            "har_entries": har_entries,
            "pages_scraped": page_data.get("pages_scraped", 0),
            "fallback_reason": fallback_reason,
        }
    finally:
        try:
            os.remove(har_path)
        except OSError:
            pass
