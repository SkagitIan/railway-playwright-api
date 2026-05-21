import json
import os
import urllib.error
import urllib.request

import pytest


BASE_URL = os.environ.get(
    "RAILWAY_API_BASE_URL",
    "https://railway-playwright-api-production.up.railway.app",
).rstrip("/")

TEST_TARGET_URL = os.environ.get(
    "TEST_TARGET_URL",
    "https://example.com",
)

JOB_TARGET_URL = os.environ.get("JOB_TARGET_URL", TEST_TARGET_URL)


def post_json(path, payload, timeout=120):
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        pytest.fail(f"{path} returned HTTP {exc.code}: {detail}")


def test_home_returns_ok():
    with urllib.request.urlopen(f"{BASE_URL}/", timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert body == {"status": "ok"}


def test_extract_links_contract():
    status, body = post_json("/extract-links", {"url": TEST_TARGET_URL})

    assert status == 200
    assert body["url"] == TEST_TARGET_URL
    assert isinstance(body["likely_job_links"], list)
    assert isinstance(body["total_links"], int)


def test_extract_page_text_contract():
    status, body = post_json("/extract-page-text", {"url": TEST_TARGET_URL})

    assert status == 200
    assert body["url"] == TEST_TARGET_URL
    assert body["final_url"].startswith("http")
    assert isinstance(body["title"], str)
    assert isinstance(body["text"], str)
    assert isinstance(body["links"], list)


@pytest.mark.skipif(
    os.environ.get("RUN_AI_ENDPOINT_TESTS") != "1",
    reason="Set RUN_AI_ENDPOINT_TESTS=1 to test OpenAI-backed endpoints.",
)
def test_analyze_network_fallback_contract():
    status, body = post_json(
        "/analyze-network-fallback",
        {"url": JOB_TARGET_URL},
        timeout=600,
    )

    assert status == 200
    assert isinstance(body["requires_browser"], bool)
    assert body["method"] in {"GET", "POST", "NONE"}
    assert isinstance(body["required_headers"], dict)
    assert "api_target_url" in body
    assert "payload" in body
    assert "json_path_to_listings" in body
    assert isinstance(body["explanation"], str)


@pytest.mark.skipif(
    os.environ.get("RUN_AI_ENDPOINT_TESTS") != "1",
    reason="Set RUN_AI_ENDPOINT_TESTS=1 to test OpenAI-backed endpoints.",
)
def test_extract_jobs_ai_contract():
    status, body = post_json(
        "/extract-jobs-ai",
        {"url": JOB_TARGET_URL},
        timeout=600,
    )

    assert status == 200
    assert body["source_url"].startswith("http")
    assert "page_title" in body
    assert "company_name" in body
    assert isinstance(body["jobs"], list)
    assert "notes" in body
