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


def test_acquirer_does_not_cache_empty_raw_data(monkeypatch):
    from scraper.stages import acquirer

    async def fake_empty_browser_har(stage_input, fallback_reason):
        return {
            "source_url": stage_input["url"],
            "data_type": "html",
            "text": None,
            "container_html": None,
            "links": [],
            "json_body": None,
            "har_entries": [],
            "pages_scraped": 0,
            "fallback_reason": fallback_reason,
        }

    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_acquire_browser_har", fake_empty_browser_har)

    stage_input = {
        "url": "https://example.com/jobs",
        "domain": "example.com",
        "classification": {"strategy": "BROWSER_HAR"},
    }

    first = asyncio.run(acquirer.run(stage_input))
    second = asyncio.run(acquirer.run(stage_input))

    assert first["acquisition_strategy"] == "har_analysis_and_ai_spec"
    assert second["acquisition_strategy"] == "har_analysis_and_ai_spec"


def test_acquirer_renders_promoted_browser_target(monkeypatch):
    from scraper.stages import acquirer

    captured = {}

    async def fake_browser_har(stage_input, fallback_reason):
        captured["acquisition_url"] = stage_input.get("acquisition_url")
        return {
            "requested_url": stage_input["url"],
            "source_url": stage_input.get("acquisition_url"),
            "final_url": stage_input.get("acquisition_url"),
            "data_type": "html",
            "text": "Senior Engineer",
            "links": [{"text": "Senior Engineer", "href": "https://ats.rippling.com/example/jobs/1"}],
            "json_body": None,
            "har_entries": [],
            "pages_scraped": 1,
            "fallback_reason": fallback_reason,
        }

    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_acquire_browser_har", fake_browser_har)

    stage_input = {
        "url": "https://example.com/careers",
        "domain": "example.com",
        "classification": {
            "strategy": "PROMOTED_SPEC",
            "ats": "rippling",
            "spec": {
                "data_delivery_type": "html_page",
                "browser_target_url": "https://ats.rippling.com/example/jobs",
                "api_target_url": None,
                "method": "NONE",
            },
        },
    }

    result = asyncio.run(acquirer.run(stage_input))

    assert captured["acquisition_url"] == "https://ats.rippling.com/example/jobs"
    assert result["raw_data"]["source_url"] == "https://ats.rippling.com/example/jobs"


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


def test_v2_jobs_greenhouse_direct_json(monkeypatch):
    client = TestClient(main.app)

    import scraper.stages.acquirer as acquirer
    import scraper.stages.classifier as classifier
    import scraper.pipeline as pipeline

    async def fake_fetch_json(*args, **kwargs):
        return {
            "jobs": [
                {
                    "title": "Software Engineer",
                    "absolute_url": "https://boards.greenhouse.io/openai/jobs/1",
                    "location": {"name": "San Francisco, CA"},
                    "departments": [{"name": "Engineering"}],
                }
            ]
        }

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(pipeline, "save_observation", lambda *args, **kwargs: None)

    response = client.post("/v2/jobs", json={"url": "https://boards.greenhouse.io/openai"})
    body = response.json()

    assert response.status_code == 200
    assert body["classification"]["strategy"] == "DIRECT_JSON_API"
    assert body["acquisition_strategy"] == "ats_deterministic"
    assert body["validation"]["success"] is True
    assert body["jobs"][0]["title"] == "Software Engineer"


def test_v2_jobs_browser_ai_empty_attaches_fallback(monkeypatch):
    client = TestClient(main.app)

    import scraper.stages.acquirer as acquirer
    import scraper.stages.classifier as classifier
    import scraper.stages.extractor as extractor
    import scraper.pipeline as pipeline

    async def fake_browser_har(stage_input, fallback_reason):
        return {
            "source_url": stage_input["url"],
            "final_url": stage_input["url"],
            "title": "Careers",
            "data_type": "html",
            "text": "Careers page",
            "container_html": None,
            "links": [],
            "json_body": None,
            "har_entries": [{"url": "https://api.example.com/jobs", "method": "GET"}],
            "pages_scraped": 1,
            "fallback_reason": fallback_reason,
        }

    async def fake_extract_jobs_from_page_data(data):
        return {"source_url": data["final_url"], "page_title": data["title"], "company_name": None, "jobs": [], "notes": "none"}

    async def fake_build_fallback_spec(source_url, har_entries):
        return {
            "data_delivery_type": "json_api",
            "requires_browser": False,
            "browser_target_url": None,
            "api_target_url": "https://api.example.com/jobs",
            "method": "GET",
            "required_headers": {"accept": None, "content_type": None, "authorization": None, "user_agent": None, "referer": None},
            "payload": None,
            "json_path_to_listings": "jobs",
            "explanation": "fixture",
        }

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_acquire_browser_har", fake_browser_har)
    monkeypatch.setattr(extractor, "extract_jobs_from_page_data", fake_extract_jobs_from_page_data)
    monkeypatch.setattr(extractor, "build_fallback_spec_from_logs", fake_build_fallback_spec)
    monkeypatch.setattr(pipeline, "save_observation", lambda *args, **kwargs: None)

    response = client.post("/v2/jobs", json={"url": "https://example.com/careers"})
    body = response.json()

    assert response.status_code == 200
    assert body["validation"]["success"] is False
    assert body["network_fallback_spec"]["api_target_url"] == "https://api.example.com/jobs"


def test_v2_jobs_retries_har_discovered_browser_target(monkeypatch):
    client = TestClient(main.app)

    import scraper.pipeline as pipeline
    import scraper.stages.acquirer as acquirer
    import scraper.stages.classifier as classifier
    import scraper.stages.extractor as extractor

    calls = []

    async def fake_browser_har(stage_input, fallback_reason):
        calls.append(stage_input.get("acquisition_url") or stage_input["url"])
        if len(calls) == 1:
            return {
                "source_url": stage_input["url"],
                "final_url": stage_input["url"],
                "title": "Careers",
                "data_type": "html",
                "text": "Careers\nJob Openings",
                "container_html": None,
                "links": [],
                "json_body": None,
                "har_entries": [
                    {
                        "url": "https://ats.rippling.com/embed/example/jobs",
                        "method": "GET",
                        "status": 200,
                        "resource_type": "text/html",
                    }
                ],
                "pages_scraped": 1,
                "fallback_reason": fallback_reason,
            }
        return {
            "source_url": stage_input.get("acquisition_url"),
            "final_url": stage_input.get("acquisition_url"),
            "title": "Jobs",
            "data_type": "html",
            "text": "Senior Engineer\nRemote",
            "container_html": None,
            "links": [{"text": "Senior Engineer", "href": "https://ats.rippling.com/example/jobs/1"}],
            "json_body": None,
            "har_entries": [],
            "pages_scraped": 1,
            "fallback_reason": fallback_reason,
        }

    async def fake_extract_jobs_from_page_data(data):
        return {"source_url": data["final_url"], "page_title": data["title"], "company_name": None, "jobs": [], "notes": "none"}

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_acquire_browser_har", fake_browser_har)
    monkeypatch.setattr(extractor, "extract_jobs_from_page_data", fake_extract_jobs_from_page_data)
    monkeypatch.setattr(pipeline, "save_observation", lambda *args, **kwargs: None)

    response = client.post("/v2/jobs", json={"url": "https://example.com/careers"})
    body = response.json()

    assert response.status_code == 200
    assert calls == ["https://example.com/careers", "https://ats.rippling.com/embed/example/jobs"]
    assert body["validation"]["success"] is True
    assert body["jobs"][0]["title"] == "Senior Engineer"


def test_v2_jobs_empty_final_result_has_useful_reason(monkeypatch):
    client = TestClient(main.app)

    import scraper.pipeline as pipeline
    import scraper.stages.acquirer as acquirer
    import scraper.stages.classifier as classifier
    import scraper.stages.extractor as extractor

    async def fake_browser_har(stage_input, fallback_reason):
        return {
            "source_url": stage_input.get("acquisition_url") or stage_input["url"],
            "final_url": stage_input.get("acquisition_url") or stage_input["url"],
            "title": "Jobs",
            "data_type": "html",
            "text": "No open roles",
            "container_html": None,
            "links": [],
            "json_body": None,
            "har_entries": [],
            "pages_scraped": 1,
            "fallback_reason": fallback_reason,
        }

    async def fake_extract_jobs_from_page_data(data):
        return {"source_url": data["final_url"], "page_title": data["title"], "company_name": None, "jobs": [], "notes": "none"}

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_acquire_browser_har", fake_browser_har)
    monkeypatch.setattr(extractor, "extract_jobs_from_page_data", fake_extract_jobs_from_page_data)
    monkeypatch.setattr(pipeline, "save_observation", lambda *args, **kwargs: None)

    response = client.post("/v2/jobs", json={"url": "https://example.com/careers"})
    body = response.json()

    assert response.status_code == 200
    assert body["validation"]["success"] is False
    assert body["debug"]["fallback_reason"] != "none"


def test_v2_jobs_extracts_rendered_table_text_without_ai(monkeypatch):
    client = TestClient(main.app)

    import scraper.pipeline as pipeline
    import scraper.stages.acquirer as acquirer
    import scraper.stages.classifier as classifier
    import scraper.stages.extractor as extractor

    async def fake_browser_har(stage_input, fallback_reason):
        return {
            "source_url": stage_input["url"],
            "final_url": stage_input["url"],
            "title": "Careers",
            "data_type": "html",
            "text": (
                "35 jobs found\n"
                "Job Title \tJob Type\tDepartment\tLocation\tSalary \tClosing \n"
                "A Role\tExempt\tEngineering\tMount Vernon, WA\t$1.00 - $2.00 Hourly\t\n"
                "B Role\tTemporary\tOperations\tOak Harbor, WA\tSee Position Description\t05/25/26\n"
                " Prev\n"
                "--- PAGE BREAK ---\n"
                "Job Title \tJob Type\tDepartment\tLocation\tSalary \tClosing \n"
                "C Role\tClassified - Permanent, Scheduled\tFinance\tAnacortes, WA\t$3,000.00 Monthly\t\n"
                "Next\n"
            ),
            "container_html": None,
            "links": [
                {"text": "A Role", "href": "https://example.com/jobs/1/a-role"},
                {"text": "B Role", "href": "https://example.com/jobs/2/b-role"},
                {"text": "C Role", "href": "https://example.com/jobs/3/c-role"},
            ],
            "json_body": None,
            "har_entries": [],
            "pages_scraped": 2,
            "fallback_reason": fallback_reason,
        }

    async def fail_ai(data):
        raise AssertionError("AI should not run for tabular rendered job text")

    monkeypatch.setattr(classifier, "get_promoted_spec", lambda domain: None)
    monkeypatch.setattr(acquirer, "_SPEC_CACHE", {})
    monkeypatch.setattr(acquirer, "_acquire_browser_har", fake_browser_har)
    monkeypatch.setattr(extractor, "extract_jobs_from_page_data", fail_ai)
    monkeypatch.setattr(pipeline, "save_observation", lambda *args, **kwargs: None)

    response = client.post("/v2/jobs", json={"url": "https://example.com/careers"})
    body = response.json()

    assert response.status_code == 200
    assert body["validation"]["success"] is True
    assert body["validation"]["job_count"] == 3
    assert [job["title"] for job in body["jobs"]] == ["A Role", "B Role", "C Role"]
