import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
import json
from fastapi.testclient import TestClient
import main


class _FakeResponse:
    def __init__(self, payload):
        self.output_text = json.dumps(payload)
        self.output = []


class _FakeResponsesAPI:
    def __init__(self, payload):
        self._payload = payload

    def create(self, **kwargs):
        return _FakeResponse(self._payload)


class _FakeClient:
    def __init__(self, payload):
        self.responses = _FakeResponsesAPI(payload)

    def with_options(self, **kwargs):
        return self


client = TestClient(main.app)


def test_extract_page_text_smoke(monkeypatch):
    async def fake_get_page_data(url):
        return {"url": url, "final_url": url, "title": "Jobs", "text": "Role A", "links": [], "pages_scraped": 1}

    monkeypatch.setattr(main, "get_page_data", fake_get_page_data)
    resp = client.post("/extract-page-text", json={"url": "https://example.com/jobs"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Jobs"


def test_extract_links_smoke(monkeypatch):
    async def fake_get_page_data(url):
        return {
            "url": url,
            "links": [
                {"text": "Careers", "href": "https://example.com/careers"},
                {"text": "Blog", "href": "https://example.com/blog"},
            ],
        }

    monkeypatch.setattr(main, "get_page_data", fake_get_page_data)
    resp = client.post("/extract-links", json={"url": "https://example.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_links"] == 2
    assert len(body["likely_job_links"]) == 1


def test_analyze_network_fallback_smoke(monkeypatch):
    async def fake_get_page_data_and_har(url, har_path):
        return {"url": url}

    async def fake_get_har_entries(path):
        return [{"url": "https://api.example.com/jobs", "status": 200}]

    async def fake_build(url, logs):
        return {"data_delivery_type": "json_api", "requires_browser": False, "browser_target_url": None, "api_target_url": logs[0]["url"], "method": "GET", "required_headers": {"accept": None, "content_type": None, "authorization": None, "user_agent": None, "referer": None}, "payload": None, "json_path_to_listings": "jobs", "explanation": "fixture"}

    monkeypatch.setattr(main, "get_page_data_and_har", fake_get_page_data_and_har)
    monkeypatch.setattr(main, "get_har_entries", fake_get_har_entries)
    monkeypatch.setattr(main, "build_fallback_spec_from_logs", fake_build)

    resp = client.post("/analyze-network-fallback", json={"url": "https://example.com/jobs"})
    assert resp.status_code == 200
    assert resp.json()["api_target_url"] == "https://api.example.com/jobs"


def test_extract_jobs_ai_smoke(monkeypatch):
    async def fake_get_page_data_and_har(url, har_path):
        return {"final_url": url, "title": "Jobs", "text": "Software Engineer", "links": [{"text": "Software Engineer", "href": "https://example.com/jobs/1"}]}

    monkeypatch.setattr(main, "get_page_data_and_har", fake_get_page_data_and_har)
    monkeypatch.setattr(main, "client", _FakeClient({"source_url": "https://example.com/jobs", "page_title": "Jobs", "company_name": "Example", "jobs": [], "notes": "none"}))

    resp = client.post("/extract-jobs-ai", json={"url": "https://example.com/jobs"})
    assert resp.status_code == 200
    assert "jobs" in resp.json()
