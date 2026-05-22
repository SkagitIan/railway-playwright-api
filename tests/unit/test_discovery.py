import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from scraper import discovery
from scraper.discovery_store import (
    create_discovery_run,
    delete_discovery_items,
    get_or_create_discovery_run,
    get_discovery_run,
    get_google_usage,
    move_discovery_items,
    reserve_google_usage,
    upsert_discovery_item,
)


def _place(place_id="place-1", name="Skagit Widget Co"):
    return {
        "id": place_id,
        "name": f"places/{place_id}",
        "displayName": {"text": name, "languageCode": "en"},
        "formattedAddress": "100 Example St, Mount Vernon, WA 98273",
        "shortFormattedAddress": "100 Example St",
        "websiteUri": "https://example.com",
        "googleMapsUri": "https://maps.google.com/?cid=1",
        "types": ["manufacturer"],
        "primaryType": "manufacturer",
        "businessStatus": "OPERATIONAL",
    }


def test_places_field_mask_includes_website_uri_and_pro_fields():
    assert "places.websiteUri" in discovery.PLACES_FIELD_MASK
    assert "places.displayName" in discovery.PLACES_FIELD_MASK
    assert "places.formattedAddress" in discovery.PLACES_FIELD_MASK
    assert "places.location" in discovery.PLACES_FIELD_MASK
    assert "places.googleMapsUri" in discovery.PLACES_FIELD_MASK
    assert "places.reviews" not in discovery.PLACES_FIELD_MASK
    assert "places.generativeSummary" not in discovery.PLACES_FIELD_MASK


def test_quota_guard_hard_stops(tmp_path):
    db_path = tmp_path / "quota.sqlite3"

    assert reserve_google_usage(2, 3, db_path=db_path)["used"] == 2
    try:
        reserve_google_usage(2, 3, db_path=db_path)
    except ValueError as exc:
        assert "monthly limit" in str(exc)
    else:
        raise AssertionError("quota guard should reject calls over limit")

    assert get_google_usage(3, db_path=db_path)["used"] == 2


def test_discovery_persistence_dedupes_by_place_id(tmp_path):
    db_path = tmp_path / "discovery.sqlite3"
    run_id = create_discovery_run("Manufacturing", "Manufacturing", discovery.SKAGIT_CITIES, db_path=db_path)

    first_id = upsert_discovery_item(run_id, "Manufacturing", "Mount Vernon", _place(), db_path=db_path)
    second_id = upsert_discovery_item(run_id, "Manufacturing", "Burlington", _place(), db_path=db_path)
    run = get_discovery_run(run_id, db_path=db_path)

    assert first_id == second_id
    assert len(run["items"]) == 1
    assert run["items"][0]["place_id"] == "place-1"
    assert run["items"][0]["website_uri"] == "https://example.com"
    assert run["items"][0]["raw_google_place"]["displayName"]["text"] == "Skagit Widget Co"


def test_delete_discovery_items_removes_selected_rows(tmp_path):
    db_path = tmp_path / "delete.sqlite3"
    run_id = create_discovery_run("Manufacturing", "Manufacturing", discovery.SKAGIT_CITIES, db_path=db_path)
    first_id = upsert_discovery_item(run_id, "Manufacturing", "Mount Vernon", _place("place-1"), db_path=db_path)
    second_id = upsert_discovery_item(run_id, "Manufacturing", "Burlington", _place("place-2"), db_path=db_path)

    assert delete_discovery_items(run_id, [first_id], db_path=db_path) == 1

    run = get_discovery_run(run_id, db_path=db_path)
    assert [item["id"] for item in run["items"]] == [second_id]


def test_move_discovery_items_to_another_industry_run(tmp_path):
    db_path = tmp_path / "move.sqlite3"
    source_run_id = create_discovery_run("Aerospace", "Aerospace", discovery.SKAGIT_CITIES, db_path=db_path)
    target_run_id = get_or_create_discovery_run("Manufacturing", "Manufacturing", discovery.SKAGIT_CITIES, db_path=db_path)
    item_id = upsert_discovery_item(source_run_id, "Aerospace", "Burlington", _place("place-1"), db_path=db_path)

    assert move_discovery_items(source_run_id, [item_id], target_run_id, "Manufacturing", db_path=db_path) == 1

    assert get_discovery_run(source_run_id, db_path=db_path)["items"] == []
    target_items = get_discovery_run(target_run_id, db_path=db_path)["items"]
    assert len(target_items) == 1
    assert target_items[0]["place_id"] == "place-1"
    assert target_items[0]["query"] == "Manufacturing"


def test_skagit_place_filter_rejects_out_of_area_results():
    skagit_place = _place() | {
        "addressComponents": [
            {"longText": "Washington", "shortText": "WA", "types": ["administrative_area_level_1"]},
            {"longText": "Skagit County", "shortText": "Skagit County", "types": ["administrative_area_level_2"]},
        ],
    }
    kirkland_place = _place(name="Kirkland Widget Co") | {
        "formattedAddress": "100 Example St, Kirkland, WA 98033",
        "addressComponents": [
            {"longText": "Washington", "shortText": "WA", "types": ["administrative_area_level_1"]},
            {"longText": "King County", "shortText": "King County", "types": ["administrative_area_level_2"]},
            {"longText": "Kirkland", "shortText": "Kirkland", "types": ["locality"]},
            {"longText": "98033", "shortText": "98033", "types": ["postal_code"]},
        ],
    }
    oregon_place = _place(name="Oregon Widget Co") | {
        "formattedAddress": "100 Example St, Portland, OR 97201",
        "addressComponents": [
            {"longText": "Oregon", "shortText": "OR", "types": ["administrative_area_level_1"]},
            {"longText": "97201", "shortText": "97201", "types": ["postal_code"]},
        ],
    }

    assert discovery._is_skagit_place(skagit_place)
    assert not discovery._is_skagit_place(kirkland_place)
    assert not discovery._is_skagit_place(oregon_place)


def test_discovery_requires_google_website_url():
    assert discovery._is_discoverable_place(_place())
    assert not discovery._is_discoverable_place(_place() | {"websiteUri": None})


def test_aerospace_filter_rejects_unrelated_places():
    campsite = _place(name="Skagit River Campsite") | {
        "primaryType": "campground",
        "types": ["campground", "lodging"],
    }
    aerospace_shop = _place(name="Skagit Aerospace Machining") | {
        "primaryType": "manufacturer",
        "types": ["manufacturer", "machine_shop"],
    }

    assert not discovery._is_discoverable_place(campsite, industry="Aerospace")
    assert discovery._is_discoverable_place(aerospace_shop, industry="Aerospace")


def test_search_city_uses_skagit_location_restriction(monkeypatch):
    payloads = []

    def fake_google_text_search(payload):
        payloads.append(payload)
        return {"places": []}

    monkeypatch.setattr(discovery, "_google_text_search", fake_google_text_search)

    pages = asyncio.run(discovery._search_city("Manufacturing", "Mount Vernon", max_pages=1))

    assert pages == [{"places": []}]
    assert payloads[0]["textQuery"] == "Manufacturing business in Mount Vernon, Skagit County, WA"
    assert payloads[0]["locationRestriction"] == discovery.SKAGIT_LOCATION_RESTRICTION
    assert payloads[0]["regionCode"] == "US"
    assert payloads[0]["includePureServiceAreaBusinesses"] is False


def test_search_city_uses_specific_aerospace_terms(monkeypatch):
    payloads = []

    def fake_google_text_search(payload):
        payloads.append(payload)
        return {"places": []}

    monkeypatch.setattr(discovery, "_google_text_search", fake_google_text_search)

    asyncio.run(discovery._search_city("Aerospace", "Burlington", max_pages=1))

    assert "aerospace manufacturer" in payloads[0]["textQuery"]
    assert "Burlington, Skagit County, WA" in payloads[0]["textQuery"]


def test_discovery_api_with_mocked_google(monkeypatch):
    client = TestClient(main.app)

    async def fake_run_discovery(industry, custom_query=None):
        return {
            "id": 1,
            "query": custom_query or industry,
            "status": "complete",
            "items": [{"place_id": "place-1", "website_uri": "https://example.com"}],
        }

    monkeypatch.setattr(discovery, "run_discovery", fake_run_discovery)

    response = client.post("/v2/discovery/runs", json={"industry": "Manufacturing"})
    body = response.json()

    assert response.status_code == 200
    assert body["query"] == "Manufacturing"
    assert len(body["items"]) == 1
    assert body["items"][0]["website_uri"] == "https://example.com"


def test_resolve_source_uses_heuristic_without_openai(tmp_path):
    run_id = create_discovery_run("Manufacturing", "Manufacturing", discovery.SKAGIT_CITIES, db_path=tmp_path / "heuristic.sqlite3")
    item_id = upsert_discovery_item(
        run_id,
        "Manufacturing",
        "Mount Vernon",
        _place(name="Example Careers") | {"websiteUri": "https://example.com/careers"},
        db_path=tmp_path / "heuristic.sqlite3",
    )
    item = get_discovery_run(run_id, db_path=tmp_path / "heuristic.sqlite3")["items"][0]

    result = asyncio.run(discovery.resolve_source_for_item(item))

    assert item["id"] == item_id
    assert result["source_url"] == "https://example.com/careers"
    assert result["source_type"] == "company_careers"


def test_resolve_source_runs_third_party_second_pass_when_primary_not_found(monkeypatch):
    calls = []
    responses = [
        {
            "source_url": None,
            "source_type": "not_found",
            "confidence": 20,
            "reason": "No official careers page found.",
            "citations": [],
        },
        {
            "source_url": "https://www.indeed.com/cmp/Skagit-Widget-Co/jobs",
            "source_type": "third_party",
            "confidence": 78,
            "reason": "Indeed has an employer-scoped jobs page.",
            "citations": ["https://www.indeed.com/cmp/Skagit-Widget-Co/jobs"],
        },
    ]

    async def fake_web_search_structured_response(*, prompt, text_format, max_output_tokens):
        calls.append(prompt)
        return SimpleNamespace(output_text=json.dumps(responses.pop(0)))

    monkeypatch.setattr(discovery, "web_search_structured_response", fake_web_search_structured_response)

    result = asyncio.run(discovery.resolve_source_for_item(_place() | {"websiteUri": "https://example.com"}))

    assert len(calls) == 2
    assert "Prefer the company's own careers/jobs page" in calls[0]
    assert "third-party job sites" in calls[1]
    assert "Indeed" in calls[1]
    assert result["source_url"] == "https://www.indeed.com/cmp/Skagit-Widget-Co/jobs"
    assert result["source_type"] == "third_party"


def test_run_jobs_resolves_source_before_running_pipeline(monkeypatch):
    calls = []
    item = {
        "id": 123,
        "name": "Skagit Widget Co",
        "formatted_address": "100 Example St, Mount Vernon, WA 98273",
        "website_uri": "https://example.com",
        "source_url": None,
    }

    async def fake_resolve_source_for_item(received_item):
        calls.append(("resolve", received_item["id"]))
        return {
            "source_url": "https://example.com/careers",
            "source_type": "company_careers",
            "confidence": 91,
            "reason": "found careers page",
            "citations": ["https://example.com/careers"],
        }

    async def fake_run_pipeline(payload):
        calls.append(("pipeline", payload["url"]))
        return {"validation": {"success": True}}

    monkeypatch.setattr(discovery, "get_discovery_items", lambda run_id, item_ids: [item])
    monkeypatch.setattr(discovery, "resolve_source_for_item", fake_resolve_source_for_item)
    monkeypatch.setattr(discovery, "update_discovery_source", lambda item_id, payload: calls.append(("source", item_id, payload["source_url"])))
    monkeypatch.setattr(discovery, "update_discovery_jobs", lambda item_id, **kwargs: calls.append(("jobs", item_id, kwargs["status"])))
    monkeypatch.setattr(discovery, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(discovery, "save_pipeline_run", lambda result, duration_ms=None: 456)
    monkeypatch.setattr(discovery, "get_run", lambda run_id: {"id": run_id, "items": []})

    result = asyncio.run(discovery.run_jobs_for_items(1, [123]))

    assert calls == [
        ("resolve", 123),
        ("source", 123, "https://example.com/careers"),
        ("jobs", 123, "running"),
        ("pipeline", "https://example.com/careers"),
        ("jobs", 123, "success"),
    ]
    assert result["results"] == [{"item_id": 123, "status": "success", "pipeline_run_id": 456}]
