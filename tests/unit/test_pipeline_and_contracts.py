import asyncio

from fastapi.testclient import TestClient

import main
from scraper.pipeline import run as pipeline_run


def test_classifier_unit_prefers_promoted_spec(monkeypatch):
    from scraper.stages import classifier

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: {"ats": "greenhouse"})
    result = asyncio.run(classifier.run({"url": "https://example.com/jobs"}))
    assert result["classification"]["strategy"] == "PROMOTED_SPEC"
    assert result["classification"]["ats"] == "greenhouse"


def test_validator_unit_counts_jobs():
    from scraper.stages import validator

    result = asyncio.run(validator.run({"jobs": [{"title": "Engineer"}]}))
    assert result["validation"]["success"] is True
    assert result["validation"]["job_count"] == 1


def test_pipeline_integration_success(monkeypatch):
    from scraper.stages import acquirer, extractor, classifier

    async def fake_acquire(stage_input):
        return {**stage_input, "raw_data": {"text": "", "links": [], "json_body": {"jobs": [{"title": "A"}]}}}

    async def fake_extract(stage_input):
        return {**stage_input, "jobs": [{"title": "A"}], "token_usage": {}}

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "run", fake_acquire)
    monkeypatch.setattr(extractor, "run", fake_extract)

    result = asyncio.run(pipeline_run({"url": "https://example.com/jobs"}))
    assert result["validation"]["success"] is True
    assert len(result["jobs"]) == 1


def test_failure_malformed_json_path(monkeypatch):
    from scraper.stages import acquirer, classifier

    async def bad_acquire(stage_input):
        return {**stage_input, "raw_data": {"text": "", "links": [], "json_body": "bad-json-type"}}

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "run", bad_acquire)

    result = asyncio.run(pipeline_run({"url": "https://example.com/jobs"}))
    assert result["validation"]["success"] is False
    assert result["validation"]["notes"] == "No jobs extracted yet"


def test_contract_v2_jobs_response_shape(monkeypatch):
    client = TestClient(main.app)

    async def fake_pipeline(payload):
        return {
            "url": payload["url"],
            "jobs": [],
            "validation": {"success": False, "job_count": 0, "notes": "No jobs extracted yet"},
            "classification": {"strategy": "BROWSER_HAR"},
        }

    import scraper.api as api

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    response = client.post("/v2/jobs", json={"url": "https://example.com/jobs"})
    body = response.json()

    assert response.status_code == 200
    assert set(["url", "jobs", "validation", "classification"]).issubset(body.keys())


def test_light_load_no_browser_leak(monkeypatch):
    client = TestClient(main.app)

    async def fake_pipeline(payload):
        return {"url": payload["url"], "jobs": [], "validation": {"success": False, "job_count": 0, "notes": "No jobs extracted yet"}, "classification": {"strategy": "BROWSER_HAR"}}

    import scraper.api as api

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)

    for i in range(20):
        response = client.post("/v2/jobs", json={"url": f"https://example.com/jobs/{i}"})
        assert response.status_code == 200
