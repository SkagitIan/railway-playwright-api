import asyncio
import json

from fastapi.testclient import TestClient

import main
from scraper import discovery
from scraper.discovery_store import (
    create_discovery_run,
    get_discovery_run,
    get_google_usage,
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
