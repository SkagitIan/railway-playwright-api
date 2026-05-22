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

from scraper.ai.client import discovery_classifier_structured_response, web_search_structured_response
from scraper.ai.parsers import parse_json_output
from scraper.config import (
    DISCOVERY_MAX_PAGES_PER_CITY,
    DISCOVERY_CLASSIFY_CONCURRENCY,
    GOOGLE_PLACES_API_KEY,
    GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT,
)
from scraper.discovery_store import (
    create_discovery_run,
    delete_discovery_items,
    get_or_create_discovery_run,
    get_discovery_items,
    get_discovery_run,
    get_google_usage,
    list_discovery_runs,
    move_discovery_items,
    reserve_google_usage,
    update_discovery_error,
    update_discovery_jobs,
    update_discovery_classification,
    update_discovery_run,
    update_discovery_source,
    upsert_discovery_item,
)
from scraper.pipeline import run as run_pipeline
from scraper.ats.spec_store import save_pipeline_run
from scraper.schemas import DISCOVERY_CLASSIFICATION_RESPONSE_FORMAT, DISCOVERY_SOURCE_RESPONSE_FORMAT


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

COMMON_EXCLUDED_PLACE_TYPES = {
    "restaurant",
    "food",
    "lodging",
    "campground",
    "rv_park",
    "tourist_attraction",
    "apartment_complex",
    "real_estate_agency",
    "bar",
    "night_club",
    "park",
}

INDUSTRY_RECIPES = {
    "Manufacturing": {
        "queries": ["manufacturer", "fabrication shop", "machine shop", "industrial supplier"],
        "included_types": ["manufacturer"],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES,
        "positive_signals": ["manufacturer", "fabrication", "machining", "industrial", "production", "assembly"],
        "negative_signals": ["restaurant", "hotel", "apartment", "campground", "retail", "salon"],
    },
    "Healthcare": {
        "queries": ["healthcare clinic", "medical center", "dental clinic", "therapy clinic"],
        "included_types": [],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES,
        "positive_signals": ["clinic", "medical", "health", "dental", "therapy", "care"],
        "negative_signals": ["restaurant", "lodging", "campground", "apartment"],
    },
    "Construction": {
        "queries": ["construction contractor", "general contractor", "builder", "excavation contractor"],
        "included_types": [],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES,
        "positive_signals": ["construction", "contractor", "builder", "concrete", "roofing", "excavation"],
        "negative_signals": ["restaurant", "lodging", "campground", "apartment"],
    },
    "Logistics": {
        "queries": ["logistics company", "trucking company", "warehouse", "freight company"],
        "included_types": [],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES,
        "positive_signals": ["logistics", "freight", "trucking", "warehouse", "transport", "distribution"],
        "negative_signals": ["restaurant", "lodging", "campground", "apartment", "retail"],
    },
    "Food Processing": {
        "queries": ["food processing manufacturer", "seafood processor", "food manufacturer", "packing company"],
        "included_types": ["manufacturer"],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES | {"restaurant", "cafe", "bakery", "meal_takeaway"},
        "positive_signals": ["processing", "processor", "packing", "manufacturer", "seafood", "food production"],
        "negative_signals": ["restaurant", "cafe", "retail", "grocery", "lodging"],
    },
    "Marine": {
        "queries": ["marine services", "boat manufacturer", "shipyard", "marine contractor"],
        "included_types": [],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES,
        "positive_signals": ["marine", "boat", "shipyard", "vessel", "dock", "maritime"],
        "negative_signals": ["restaurant", "lodging", "campground", "apartment", "yacht club"],
    },
    "Aerospace": {
        "queries": ["aerospace aircraft aviation manufacturer", "precision aerospace manufacturer", "aviation parts manufacturer"],
        "included_types": ["manufacturer"],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES | {
            "marina",
            "yacht_club",
            "local_government_office",
            "port_authority",
        },
        "positive_signals": ["aerospace", "aircraft", "aviation", "machining", "precision", "composites", "manufacturer"],
        "negative_signals": ["campground", "restaurant", "lodging", "apartment", "marina", "yacht club", "port authority"],
    },
    "Agriculture": {
        "queries": ["farm", "agriculture business", "nursery", "agricultural supplier"],
        "included_types": [],
        "excluded_types": COMMON_EXCLUDED_PLACE_TYPES,
        "positive_signals": ["farm", "agriculture", "nursery", "dairy", "seed", "crop", "grower"],
        "negative_signals": ["restaurant", "lodging", "campground", "apartment", "retail"],
    },
}

INDUSTRY_QUERY_TERMS = {
    industry: " ".join(recipe["queries"])
    for industry, recipe in INDUSTRY_RECIPES.items()
    if recipe.get("queries")
}

INDUSTRY_INCLUDED_TYPES = {
    industry: (recipe.get("included_types") or [None])[0]
    for industry, recipe in INDUSTRY_RECIPES.items()
    if recipe.get("included_types")
}

INDUSTRY_EXCLUDED_PLACE_TYPES = {
    industry: set(recipe.get("excluded_types") or set())
    for industry, recipe in INDUSTRY_RECIPES.items()
}

INDUSTRY_RESULT_KEYWORDS = {
    industry: set(recipe.get("positive_signals") or [])
    for industry, recipe in INDUSTRY_RECIPES.items()
}

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

    target_industry = industry if industry in INDUSTRY_PRESETS else query
    run_id = create_discovery_run(query=query, industry=target_industry, cities=SKAGIT_CITIES)
    actual_calls = 0
    try:
        for city in SKAGIT_CITIES:
            pages = await _search_city(query, city, max_pages=DISCOVERY_MAX_PAGES_PER_CITY)
            actual_calls += len(pages)
            for page in pages:
                for place in page.get("places", []) or []:
                    if _is_discoverable_place(place, industry=target_industry):
                        upsert_discovery_item(run_id, query, city, place)
        update_discovery_run(run_id, status="complete", google_calls=actual_calls)
        if get_discovery_items(run_id):
            await classify_items(run_id)
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


def move_items(run_id: int, item_ids: list[int], target_industry: str) -> dict[str, Any]:
    target = (target_industry or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="Target industry is required")
    if not item_ids:
        raise HTTPException(status_code=422, detail="At least one discovery row is required")
    if target not in INDUSTRY_PRESETS:
        raise HTTPException(status_code=422, detail=f"Unknown discovery industry: {target}")
    target_run_id = get_or_create_discovery_run(target, target, SKAGIT_CITIES)
    moved = move_discovery_items(run_id, item_ids, target_run_id, target)
    if moved == 0:
        raise HTTPException(status_code=404, detail="No matching discovery rows found to move")
    return {"moved": moved, "source_run": get_run(run_id), "target_run": get_run(target_run_id)}


async def classify_items(run_id: int, item_ids: list[int] | None = None) -> dict[str, Any]:
    run = get_discovery_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"No discovery run found: {run_id}")
    items = get_discovery_items(run_id, item_ids)
    if not items:
        raise HTTPException(status_code=404, detail="No discovery rows found to classify")

    target_industry = run.get("industry") or run.get("query") or ""
    semaphore = asyncio.Semaphore(max(1, DISCOVERY_CLASSIFY_CONCURRENCY))

    async def _classify(item: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                payload = await classify_item_for_industry(item, target_industry)
                update_discovery_classification(item["id"], payload)
                return {"item_id": item["id"], "status": "ok", **payload}
            except Exception as exc:
                payload = _classification_fallback(str(exc))
                update_discovery_classification(item["id"], payload)
                return {"item_id": item["id"], "status": "error", "error": str(exc), **payload}

    results = await asyncio.gather(*[_classify(item) for item in items])
    return {"run": get_run(run_id), "results": results}


async def classify_item_for_industry(item: dict[str, Any], target_industry: str) -> dict[str, Any]:
    response = await discovery_classifier_structured_response(
        prompt=_build_classification_prompt(item, target_industry),
        text_format=DISCOVERY_CLASSIFICATION_RESPONSE_FORMAT,
        max_output_tokens=700,
    )
    fallback = _classification_fallback("OpenAI did not return valid JSON.")
    payload = parse_json_output(response.output_text, fallback)
    return _normalize_classification(payload, target_industry)


def update_item_classification(run_id: int, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    items = get_discovery_items(run_id, [item_id])
    if not items:
        raise HTTPException(status_code=404, detail="No matching discovery row found")
    normalized = _normalize_classification(payload, items[0].get("query") or "")
    update_discovery_classification(item_id, normalized)
    return {"run": get_run(run_id), "item_id": item_id, "classification": normalized}


async def resolve_sources(run_id: int, item_ids: list[int] | None = None) -> dict[str, Any]:
    items = get_discovery_items(run_id, item_ids)
    if not items:
        raise HTTPException(status_code=404, detail="No discovery rows found to resolve")

    async def _resolve(item: dict[str, Any]) -> dict[str, Any]:
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

    primary = await _resolve_source_with_prompt(item, _build_primary_source_prompt(item))
    if primary.get("source_url") or primary.get("source_type") != "not_found":
        return primary

    secondary = await _resolve_source_with_prompt(item, _build_third_party_source_prompt(item))
    if secondary.get("source_url"):
        return secondary

    return {
        **primary,
        "reason": f"{primary.get('reason') or 'No official source found.'} Secondary third-party jobs search: {secondary.get('reason') or 'no credible job listings found.'}",
        "citations": list(dict.fromkeys((primary.get("citations") or []) + (secondary.get("citations") or []))),
    }


async def _resolve_source_with_prompt(item: dict[str, Any], prompt: str) -> dict[str, Any]:
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


def _build_primary_source_prompt(item: dict[str, Any]) -> str:
    website = item.get("website_uri")
    return (
        "Find the best URL that lists current job openings for this business. "
        "Prefer the company's own careers/jobs page. If the company uses an ATS, return that ATS job board URL. "
        "Use a reputable third-party job page only if no official source is visible. "
        "Return null source_url and source_type not_found if no credible jobs source exists.\n\n"
        f"Business name: {item.get('name')}\n"
        f"Address: {item.get('formatted_address') or item.get('short_formatted_address')}\n"
        f"Website from Google Places: {website or 'none'}\n"
        f"Google Maps URL: {item.get('google_maps_uri') or 'none'}"
    )


def _build_third_party_source_prompt(item: dict[str, Any]) -> str:
    return (
        "The first pass did not find an official careers page for this employer. "
        "Now search the open web specifically for active job listings or a claimed employer jobs portal on reputable third-party job sites. "
        "Prioritize pages from Indeed, LinkedIn, ZipRecruiter, Glassdoor, WorkSourceWA, government workforce boards, or recognized ATS/job-board hosts. "
        "Look for pages that appear to belong to this exact employer, using the business name and address/location to avoid similarly named companies. "
        "A good result can be an employer profile with current open roles, a search/result page scoped to the exact employer, or a specific active listing for the employer. "
        "Do not return generic web search results, unrelated directory pages, stale closed listings, review-only pages, or job pages for a different company/location. "
        "Return source_type third_party for a third-party jobs page. "
        "Return null source_url and source_type not_found if no credible active or employer-scoped job source exists.\n\n"
        f"Business name: {item.get('name')}\n"
        f"Address: {item.get('formatted_address') or item.get('short_formatted_address')}\n"
        f"Website from Google Places: {item.get('website_uri') or 'none'}\n"
        f"Google Maps URL: {item.get('google_maps_uri') or 'none'}"
    )


async def run_jobs_for_items(run_id: int, item_ids: list[int]) -> dict[str, Any]:
    items = get_discovery_items(run_id, item_ids)
    if not items:
        raise HTTPException(status_code=404, detail="No discovery rows found to run")
    results = []
    for item in items:
        source_url = item.get("source_url")
        if not source_url:
            try:
                payload = await resolve_source_for_item(item)
                update_discovery_source(item["id"], payload)
                source_url = payload.get("source_url")
            except Exception as exc:
                update_discovery_error(item["id"], source_status="error", jobs_status="error", error=str(exc))
                results.append({"item_id": item["id"], "status": "error", "error": str(exc)})
                continue
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


def _build_classification_prompt(item: dict[str, Any], target_industry: str) -> str:
    raw = item.get("raw_google_place") or item
    recipe = INDUSTRY_RECIPES.get(target_industry, {})
    place_types = raw.get("types") or item.get("types") or []
    primary_type = raw.get("primaryType") or item.get("primary_type")
    allowed_industries = ", ".join(INDUSTRY_PRESETS)
    return (
        "Classify whether this Google Places business belongs in the selected discovery industry. "
        "Use only the provided Google Places metadata; do not search the web. "
        "Return match for a clear fit, maybe for a plausible employer that needs human review, and no_match for unrelated consumer, lodging, food, recreation, apartment, government, or other wrong-category results. "
        "If no_match or maybe and another preset fits better, set suggested_industry to that preset; otherwise null.\n\n"
        f"Selected industry: {target_industry}\n"
        f"Preset industries: {allowed_industries}\n"
        f"Positive signals for selected industry: {', '.join(recipe.get('positive_signals') or []) or 'none'}\n"
        f"Negative signals for selected industry: {', '.join(recipe.get('negative_signals') or []) or 'none'}\n"
        f"Business name: {item.get('name')}\n"
        f"Address: {item.get('formatted_address') or item.get('short_formatted_address')}\n"
        f"Website URL: {item.get('website_uri') or 'none'}\n"
        f"Google place primary type: {primary_type or 'none'}\n"
        f"Google place types: {', '.join(place_types) if place_types else 'none'}\n"
        f"Search query: {item.get('query') or 'none'}\n"
        f"Search city: {item.get('city') or 'none'}"
    )


def _classification_fallback(reason: str) -> dict[str, Any]:
    return {
        "industry_fit": "maybe",
        "confidence": 0,
        "reason": reason,
        "suggested_industry": None,
        "signals": [],
        "reject_reason": None,
    }


def _normalize_classification(payload: dict[str, Any], target_industry: str) -> dict[str, Any]:
    fit = str(payload.get("industry_fit") or "maybe").lower()
    if fit not in {"match", "maybe", "no_match"}:
        fit = "maybe"
    try:
        confidence = float(payload.get("confidence") if payload.get("confidence") is not None else 0)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))
    suggested = payload.get("suggested_industry")
    if suggested not in INDUSTRY_PRESETS:
        suggested = None
    signals = payload.get("signals") or []
    if not isinstance(signals, list):
        signals = [str(signals)]
    reason = str(payload.get("reason") or "").strip() or "No classification reason returned."
    reject_reason = payload.get("reject_reason")
    if fit == "no_match" and not reject_reason:
        reject_reason = reason
    return {
        "industry_fit": fit,
        "confidence": confidence,
        "reason": reason[:500],
        "suggested_industry": suggested,
        "signals": [str(signal)[:120] for signal in signals[:8]],
        "reject_reason": str(reject_reason)[:500] if reject_reason else None,
    }


async def _search_city(query: str, city: str, max_pages: int) -> list[dict[str, Any]]:
    pages = []
    page_token = None
    for _ in range(max(1, max_pages)):
        search_terms = INDUSTRY_QUERY_TERMS.get(query, f"{query} business")
        payload: dict[str, Any] = {
            "textQuery": f"{search_terms} in {city}, Skagit County, WA",
            "locationRestriction": SKAGIT_LOCATION_RESTRICTION,
            "regionCode": "US",
            "languageCode": "en",
            "includePureServiceAreaBusinesses": False,
        }
        included_type = INDUSTRY_INCLUDED_TYPES.get(query)
        if included_type:
            payload["includedType"] = included_type
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


def _is_discoverable_place(place: dict[str, Any], industry: str | None = None) -> bool:
    return bool(place.get("id") and place.get("websiteUri") and _is_skagit_place(place) and _matches_industry(place, industry))


def _matches_industry(place: dict[str, Any], industry: str | None) -> bool:
    if not industry:
        return True
    excluded_types = INDUSTRY_EXCLUDED_PLACE_TYPES.get(industry, COMMON_EXCLUDED_PLACE_TYPES)
    place_types = {str(t).lower() for t in (place.get("types") or [])}
    primary_type = str(place.get("primaryType") or "").lower()
    if primary_type in excluded_types or place_types.intersection(excluded_types):
        return False

    return True


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
