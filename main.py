import json
import os
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import Field
from openai import APITimeoutError, OpenAI
from scraper.config import AI_MODEL, AI_TIMEOUT_SECONDS
from scraper.browser.context import fetch_page_with_context
from scraper.browser.paginator import collect_paginated_page_data
from scraper.browser.har import parse_har_entries
from scraper.models import UrlRequest
from scraper.schemas import JOB_LISTINGS_RESPONSE_FORMAT, SCRAPER_SPEC_RESPONSE_FORMAT

app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- Helper Methods ---

def empty_job_result(source_url: str, page_title: str | None, notes: str):
    return {
        "source_url": source_url,
        "page_title": page_title,
        "company_name": None,
        "jobs": [],
        "notes": notes,
    }


def default_scraper_spec(explanation: str):
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


def response_refusal(response):
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", None) or "AI refused to extract the page."
    return None


async def get_page_data(url: str):
    return await get_page_data_and_har(url, None)


async def get_page_data_and_har(url: str, har_path: str | None):
    playwright, browser, context, page = await fetch_page_with_context(url, har_path)
    try:
        title = await page.title()
        pages = await collect_paginated_page_data(page)
        final_url = page.url

        text = "\n\n--- PAGE BREAK ---\n\n".join(p["text"] for p in pages)
        links = []
        seen = set()
        for page_data in pages:
            for link in page_data["links"]:
                key = (link["text"], link["href"])
                if key not in seen:
                    seen.add(key)
                    links.append(link)

        return {
            "url": url,
            "final_url": final_url,
            "title": title,
            "text": text,
            "links": links,
            "pages_scraped": len(pages),
        }
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()

# --- REST Endpoints ---

@app.get("/")
def home():
    return {"status": "ok"}


@app.post("/extract-page-text")
async def extract_page_text(req: UrlRequest):
    return await get_page_data(req.url)


@app.post("/extract-links")
async def extract_links(req: UrlRequest):
    data = await get_page_data(req.url)

    words = ["job", "jobs", "career", "careers", "employment", "hiring", "join our team"]

    likely = [
        link for link in data["links"]
        if any(word in (link["text"] + " " + link["href"]).lower() for word in words)
    ]

    return {
        "url": req.url,
        "likely_job_links": likely[:20],
        "total_links": len(data["links"]),
    }


@app.post("/analyze-network-fallback")
async def analyze_network_fallback(req: UrlRequest):
    """
    Fallback endpoint called when no visual job listings are uncovered.
    Traces underlying API tracks, network streams, and asynchronous data loads to construct 
    an automated fetch blueprint.
    """
    tmp_file = f"network_trace_{os.getpid()}_{asyncio.get_event_loop().time()}.har"
    
    try:
        # 1. Capture page data and structural network traffic logs in one browser pass
        _ = await get_page_data_and_har(req.url, tmp_file)
        traffic_logs = parse_har_entries(tmp_file)
        
        if not traffic_logs:
            return {
                "data_delivery_type": "unknown",
                "requires_browser": True,
                "browser_target_url": req.url,
                "api_target_url": None,
                "method": "NONE",
                "required_headers": {
                    "accept": None,
                    "content_type": None,
                    "authorization": None,
                    "user_agent": None,
                    "referer": None
                },
                "payload": None,
                "json_path_to_listings": None,
                "explanation": "No network logs could be safely recorded or extracted from this URL target.",
            }

        return await build_fallback_spec_from_logs(req.url, traffic_logs)
    except asyncio.TimeoutError:
        return default_scraper_spec("Network reverse engineering request timed out.")
    except Exception as e:
        return default_scraper_spec(f"Network fallback failed safely: {str(e)}")


async def build_fallback_spec_from_logs(source_url: str, traffic_logs: list[dict]):
    # Package request traces into an analytical diagnosis prompt
    prompt = f"""
You are an advanced web scraping backend system routing requests for Applicant Tracking Systems (ATS).
Review the following filtered network logs captured via a browser rendering engine on a company careers page.

Classification Contract:
- Return data_delivery_type = "json_api" when a reproducible JSON endpoint exists.
- Return data_delivery_type = "html_page" when the HAR includes a likely jobs/careers HTML document suitable for browser rendering.
- Return data_delivery_type = "html_fragment" when async fetch/xhr requests return text/html fragments containing job listings.
- Return data_delivery_type = "unknown" when neither path is clear.

Required Output Rules:
- If data_delivery_type = "json_api": set api_target_url and provide the appropriate method, required_headers, payload, and json_path_to_listings.
- If data_delivery_type = "html_page": set browser_target_url to the best renderable jobs/careers URL; set api_target_url = null and method = "NONE" unless a real API is also clearly found.
- If data_delivery_type = "html_fragment": set api_target_url to that async endpoint and keep requires_browser=true if cookies/challenges are likely required.
- If data_delivery_type = "unknown": use nulls/"NONE" where appropriate and explain uncertainty.
- Avoid vendor-specific assumptions in your reasoning; infer only from observable network evidence.

NETWORK LOG DATA:
{json.dumps(traffic_logs, ensure_ascii=False, indent=2)}
"""

    # Call OpenAI to reverse engineer the request footprint
    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.with_options(timeout=AI_TIMEOUT_SECONDS).responses.create,
            model=AI_MODEL,
            input=prompt,
            text={"format": SCRAPER_SPEC_RESPONSE_FORMAT},
            max_output_tokens=3000,
        ),
        timeout=AI_TIMEOUT_SECONDS + 5,
    )

    refusal = response_refusal(response)
    if refusal:
        raise HTTPException(status_code=422, detail=f"AI Refusal mapping request footprint: {refusal}")

    return json.loads(response.output_text.strip())


@app.post("/extract-jobs-ai")
async def extract_jobs_ai(req: UrlRequest):
    tmp_file = f"extract_trace_{os.getpid()}_{asyncio.get_event_loop().time()}.har"
    try:
        async def extract_jobs_from_page_data(data):
            prompt = f"""
Extract job listings from this rendered careers/job page.

Rules:
- Only include real job listings.
- Exclude navigation links, generic career content, and unrelated pages.
- Use null for unknown scalar values.
- Use empty arrays when no list items are known.
- Prefer exact URLs from LINKS for job_url and apply_url.
- source_url must be: {data["final_url"]}
- confidence is 0-100.

PAGE TITLE:
{data["title"]}

VISIBLE TEXT:
{data["text"]}

LINKS:
{json.dumps(data["links"], ensure_ascii=False)}
"""
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.with_options(timeout=AI_TIMEOUT_SECONDS).responses.create,
                        model=AI_MODEL,
                        input=prompt,
                        text={"format": JOB_LISTINGS_RESPONSE_FORMAT},
                        max_output_tokens=6000,
                    ),
                    timeout=AI_TIMEOUT_SECONDS + 5,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=504,
                    detail=f"AI extraction exceeded {AI_TIMEOUT_SECONDS:.0f} seconds",
                )
            except (APITimeoutError, TimeoutError):
                raise HTTPException(
                    status_code=504,
                    detail=f"OpenAI request exceeded {AI_TIMEOUT_SECONDS:.0f} seconds",
                )

            if getattr(response, "status", None) == "incomplete":
                incomplete_details = getattr(response, "incomplete_details", None)
                reason = getattr(incomplete_details, "reason", None) or "unknown"
                return empty_job_result(
                    data["final_url"],
                    data["title"],
                    f"AI response was incomplete: {reason}",
                )

            refusal = response_refusal(response)
            if refusal:
                return empty_job_result(data["final_url"], data["title"], refusal)

            raw = response.output_text.strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return empty_job_result(
                    data["final_url"],
                    data["title"],
                    f"AI did not return valid JSON. Raw prefix: {raw[:1000]}",
                )

        data = await get_page_data_and_har(req.url, tmp_file)
        parsed_result = await extract_jobs_from_page_data(data)

        # --- THE AUTOMATED FALLBACK CHECK ---
        # If the extraction runs cleanly but yields empty arrays, automatically pivot to network fallback analysis
        if not parsed_result.get("jobs") or len(parsed_result["jobs"]) == 0:
            print(f"🔍 No explicit visual jobs found on {req.url}. Re-routing to HAR network pipeline...")
            traffic_logs = parse_har_entries(tmp_file)
            if traffic_logs:
                fallback_spec = await build_fallback_spec_from_logs(req.url, traffic_logs)
            else:
                fallback_spec = default_scraper_spec("No HAR logs captured during first-pass extraction.")
            parsed_result["network_fallback_spec"] = fallback_spec

            if fallback_spec.get("data_delivery_type") == "html_page":
                parsed_result["notes"] = (
                    (parsed_result.get("notes") or "")
                    + " [No visible jobs found. Best reusable source is browser-rendered HTML: "
                    + f"{fallback_spec.get('browser_target_url')}]"
                )
                return parsed_result

            if fallback_spec.get("data_delivery_type") == "json_api":
                parsed_result["notes"] = (
                    (parsed_result.get("notes") or "")
                    + f" [JSON API source found: {fallback_spec.get('api_target_url')}]"
                )
                return parsed_result

            parsed_result["notes"] = (
                (parsed_result.get("notes") or "")
                + " [No usable API or HTML job source found.]"
            )
            return parsed_result

        return parsed_result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass
