"""Google Places discovery and source URL resolution."""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from scraper.ai.client import web_search_structured_response
from scraper.ai.parsers import parse_json_output
from scraper.config import (
    DISCOVERY_MAX_PAGES_PER_CITY,
    DISCOVERY_SOURCE_RESOLVE_CONCURRENCY,
    GOOGLE_PLACES_API_KEY,
    GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT,
)
from scraper.discovery_store import (
    create_discovery_run,
    delete_discovery_items,
    get_discovery_items,
    get_discovery_run,
    get_google_usage,
    list_discovery_runs,
    reserve_google_usage,
    update_discovery_error,
    update_discovery_jobs,
    update_discovery_run,
    update_discovery_source,
    upsert_discovery_item,
)
from scraper.pipeline import run as run_pipeline
from scraper.ats.spec_store import save_pipeline_run
from scraper.schemas import DISCOVERY_SOURCE_RESPONSE_FORMAT


SKAGIT_CITIES = [
    "Anacortes",
    "Burlington",
    "Concrete",
    "Hamilton",
    "La Conner",
    "Lyman",
    "Mount Vernon",
    "Sedro-Woolley",
]

SKAGIT_COMMUNITIES = {city.lower() for city in SKAGIT_CITIES} | {
    "bow",
    "conway",
    "marblemount",
    "rockport",
}

SKAGIT_POSTAL_CODES = {
    "98221",
    "98232",
    "98233",
    "98235",
    "98237",
    "98238",
    "98255",
    "98257",
    "98263",
    "98267",
    "98273",
    "98274",
    "98283",
    "98284",
}

SKAGIT_LOCATION_RESTRICTION = {
    "rectangle": {
        "low": {"latitude": 48.24, "longitude": -122.74},
        "high": {"latitude": 48.74, "longitude": -121.02},
    }
}

INDUSTRY_PRESETS = [
    "Manufacturing",
    "Healthcare",
    "Construction",
    "Logistics",
    "Food Processing",
    "Marine",
    "Aerospace",
    "Agriculture",
]

GOOGLE_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.name",
        "places.displayName",
        "places.formattedAddress",
        "places.shortFormattedAddress",
        "places.addressComponents",
        "places.postalAddress",
        "places.location",
        "places.viewport",
        "places.types",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.businessStatus",
        "places.googleMapsUri",
        "places.googleMapsLinks",
        "places.photos",
        "places.timeZone",
        "places.utcOffsetMinutes",
        "places.openingDate",
        "places.accessibilityOptions",
        "places.containingPlaces",
        "places.pureServiceAreaBusiness",
        "places.subDestinations",
        "places.iconBackgroundColor",
        "places.iconMaskBaseUri",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.rating",
        "places.userRatingCount",
        "places.regularOpeningHours",
        "places.currentOpeningHours",
        "nextPageToken",
    ]
)

ATS_HOST_PARTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "rippling.com",
    "ultipro.com",
    "myworkdayjobs.com",
    "bamboohr.com",
    "smartrecruiters.com",
    "icims.com",
    "paylocity.com",
)

CAREER_PATH_RE = re.compile(r"/(?:careers?|jobs?|employment|opportunities|join-?our-?team|work-with-us)(?:/|$)", re.I)


def discovery_meta() -> dict[str, Any]:
    return {
        "industries": INDUSTRY_PRESETS,
        "cities": SKAGIT_CITIES,
        "quota": get_google_usage(GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT),
        "field_mask": PLACES_FIELD_MASK,
    }


async def run_discovery(industry: str, custom_query: str | None = None) -> dict[str, Any]:
    query = (custom_query or industry or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="Discovery query is required")
    if not (os.environ.get("GOOGLE_PLACES_API_KEY") or GOOGLE_PLACES_API_KEY):
        raise HTTPException(status_code=500, detail="GOOGLE_PLACES_API_KEY is not configured")

    estimated_calls = len(SKAGIT_CITIES) * max(1, DISCOVERY_MAX_PAGES_PER_CITY)
    try:
        reserve_google_usage(estimated_calls, GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    run_id = create_discovery_run(query=query, industry=industry, cities=SKAGIT_CITIES)
    actual_calls = 0
    try:
        for city in SKAGIT_CITIES:
            pages = await _search_city(query, city, max_pages=DISCOVERY_MAX_PAGES_PER_CITY)
            actual_calls += len(pages)
            for page in pages:
                for place in page.get("places", []) or []:
                    if place.get("id") and _is_skagit_place(place):
                        upsert_discovery_item(run_id, query, city, place)
        update_discovery_run(run_id, status="complete", google_calls=actual_calls)
    except Exception as exc:
        update_discovery_run(run_id, status="error", google_calls=actual_calls, error=str(exc))
        raise

    run = get_discovery_run(run_id)
    if not run:
        raise HTTPException(status_code=500, detail="Discovery run was not persisted")
    run["quota"] = get_google_usage(GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT)
    return run


def list_runs(limit: int = 50) -> dict[str, Any]:
    return {
        "runs": list_discovery_runs(limit=limit),
        "quota": get_google_usage(GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT),
    }


def get_run(run_id: int) -> dict[str, Any]:
    run = get_discovery_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"No discovery run found: {run_id}")
    run["quota"] = get_google_usage(GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT)
    return run


def delete_items(run_id: int, item_ids: list[int]) -> dict[str, Any]:
    if not item_ids:
        raise HTTPException(status_code=422, detail="At least one discovery row is required")
    deleted = delete_discovery_items(run_id, item_ids)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No matching discovery rows found to delete")
    return {"deleted": deleted, "run": get_run(run_id)}


async def resolve_sources(run_id: int, item_ids: list[int] | None = None) -> dict[str, Any]:
    items = get_discovery_items(run_id, item_ids)
    if not items:
        raise HTTPException(status_code=404, detail="No discovery rows found to resolve")

    sem = asyncio.Semaphore(max(1, DISCOVERY_SOURCE_RESOLVE_CONCURRENCY))

    async def _resolve(item: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                payload = await resolve_source_for_item(item)
                update_discovery_source(item["id"], payload)
                return {"item_id": item["id"], "status": "ok", **payload}
            except Exception as exc:
                update_discovery_error(item["id"], source_status="error", error=str(exc))
                return {"item_id": item["id"], "status": "error", "error": str(exc)}

    results = await asyncio.gather(*[_resolve(item) for item in items])
    return {"run": get_run(run_id), "results": results}


async def resolve_source_for_item(item: dict[str, Any]) -> dict[str, Any]:
    heuristic = _heuristic_source(item)
    if heuristic:
        return heuristic

    website = item.get("website_uri")
    prompt = (
        "Find the best URL that lists current job openings for this business. "
        "Prefer the company's own careers/jobs page. If the company uses an ATS, return that ATS job board URL. "
        "Use a reputable third-party job page only if no official source is visible. "
        "Return null source_url and source_type not_found if no credible jobs source exists.\n\n"
        f"Business name: {item.get('name')}\n"
        f"Address: {item.get('formatted_address') or item.get('short_formatted_address')}\n"
        f"Website from Google Places: {website or 'none'}\n"
        f"Google Maps URL: {item.get('google_maps_uri') or 'none'}"
    )
    response = await web_search_structured_response(
        prompt=prompt,
        text_format=DISCOVERY_SOURCE_RESPONSE_FORMAT,
        max_output_tokens=1000,
    )
    fallback = {
        "source_url": None,
        "source_type": "not_found",
        "confidence": 0,
        "reason": "OpenAI did not return valid JSON.",
        "citations": [],
    }
    return parse_json_output(response.output_text, fallback)


async def run_jobs_for_items(run_id: int, item_ids: list[int]) -> dict[str, Any]:
    items = get_discovery_items(run_id, item_ids)
    if not items:
        raise HTTPException(status_code=404, detail="No discovery rows found to run")
    results = []
    for item in items:
        source_url = item.get("source_url")
        if not source_url:
            update_discovery_error(item["id"], jobs_status="error", error="No source URL resolved")
            results.append({"item_id": item["id"], "status": "error", "error": "No source URL resolved"})
            continue
        update_discovery_jobs(item["id"], status="running")
        try:
            result = await run_pipeline({"url": source_url})
            pipeline_run_id = save_pipeline_run(result, duration_ms=None)
            success = bool((result.get("validation") or {}).get("success"))
            update_discovery_jobs(item["id"], status="success" if success else "empty", pipeline_run_id=pipeline_run_id)
            results.append({"item_id": item["id"], "status": "success" if success else "empty", "pipeline_run_id": pipeline_run_id})
        except Exception as exc:
            update_discovery_jobs(item["id"], status="error", error=str(exc))
            results.append({"item_id": item["id"], "status": "error", "error": str(exc)})
    return {"run": get_run(run_id), "results": results}


async def _search_city(query: str, city: str, max_pages: int) -> list[dict[str, Any]]:
    pages = []
    page_token = None
    for _ in range(max(1, max_pages)):
        payload: dict[str, Any] = {
            "textQuery": f"{query} business in {city}, Skagit County, WA",
            "locationRestriction": SKAGIT_LOCATION_RESTRICTION,
            "regionCode": "US",
            "languageCode": "en",
            "includePureServiceAreaBusinesses": False,
        }
        if page_token:
            payload["pageToken"] = page_token
        data = await asyncio.to_thread(_google_text_search, payload)
        pages.append(data)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        await asyncio.sleep(2)
    return pages


def _google_text_search(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TEXT_SEARCH_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": os.environ.get("GOOGLE_PLACES_API_KEY") or GOOGLE_PLACES_API_KEY or "",
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Google Places request failed: {detail}") from exc


def _is_skagit_place(place: dict[str, Any]) -> bool:
    components = place.get("addressComponents") or []
    county = _address_component(components, "administrative_area_level_2")
    if county and county.lower() == "skagit county":
        return True

    state = _address_component(components, "administrative_area_level_1")
    postal_code = _address_component(components, "postal_code")
    locality = (
        _address_component(components, "locality")
        or _address_component(components, "postal_town")
        or _address_component(components, "sublocality")
    )
    postal_address = place.get("postalAddress") or {}
    state = state or postal_address.get("administrativeArea")
    postal_code = postal_code or postal_address.get("postalCode")
    locality = locality or postal_address.get("locality")

    if state and state.upper() not in {"WA", "WASHINGTON"}:
        return False
    if postal_code and postal_code[:5] in SKAGIT_POSTAL_CODES:
        return True
    if locality and locality.lower() in SKAGIT_COMMUNITIES:
        return True

    address = f"{place.get('formattedAddress') or ''} {place.get('shortFormattedAddress') or ''}".lower()
    if not any(marker in address for marker in (" wa ", ", wa", " washington ")):
        return False
    return any(city in address for city in SKAGIT_COMMUNITIES) or any(zip_code in address for zip_code in SKAGIT_POSTAL_CODES)


def _address_component(components: list[dict[str, Any]], component_type: str) -> str | None:
    for component in components:
        if component_type in (component.get("types") or []):
            return component.get("longText") or component.get("shortText")
    return None


def _heuristic_source(item: dict[str, Any]) -> dict[str, Any] | None:
    website = item.get("website_uri")
    if not website:
        return None
    parsed = urlparse(website)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(part in host for part in ATS_HOST_PARTS):
        return {
            "source_url": website,
            "source_type": "ats",
            "confidence": 90,
            "reason": "Google website URL points directly at a known ATS domain.",
            "citations": [website],
        }
    if CAREER_PATH_RE.search(path):
        return {
            "source_url": website,
            "source_type": "company_careers",
            "confidence": 85,
            "reason": "Google website URL already appears to be a careers or jobs page.",
            "citations": [website],
        }
    return None
