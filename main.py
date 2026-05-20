import json
import os
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import Field
from openai import APITimeoutError
from scraper.config import AI_TIMEOUT_SECONDS
from scraper.browser.context import fetch_page_with_context
from scraper.browser.paginator import collect_paginated_page_data
from scraper.browser.har import parse_har_entries
from scraper.models import UrlRequest
from scraper.schemas import JOB_LISTINGS_RESPONSE_FORMAT, SCRAPER_SPEC_RESPONSE_FORMAT
from scraper.ai.client import structured_response
from scraper.ai.prompts import build_extract_jobs_prompt, build_network_fallback_prompt
from scraper.ai.parsers import parse_json_output, response_refusal

app = FastAPI()
ai_structured_response = structured_response
client = None  # Backward-compatible test hook

async def get_har_entries(path: str):
    return parse_har_entries(path)



async def request_structured_output(*, prompt: str, text_format: dict, max_output_tokens: int):
    if client is not None:
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.with_options(timeout=AI_TIMEOUT_SECONDS).responses.create,
                model="gpt-4.1-mini",
                input=prompt,
                text={"format": text_format},
                max_output_tokens=max_output_tokens,
            ),
            timeout=AI_TIMEOUT_SECONDS + 5,
        )

    return await ai_structured_response(
        prompt=prompt,
        text_format=text_format,
        max_output_tokens=max_output_tokens,
    )

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
        traffic_logs = await get_har_entries(tmp_file)
        
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
    prompt = build_network_fallback_prompt(traffic_logs)
    response = await request_structured_output(
        prompt=prompt,
        text_format=SCRAPER_SPEC_RESPONSE_FORMAT,
        max_output_tokens=3000,
    )

    refusal = response_refusal(response)
    if refusal:
        raise HTTPException(status_code=422, detail=f"AI Refusal mapping request footprint: {refusal}")

    return parse_json_output(response.output_text, default_scraper_spec("AI returned invalid JSON for fallback spec."))


@app.post("/extract-jobs-ai")
async def extract_jobs_ai(req: UrlRequest):
    tmp_file = f"extract_trace_{os.getpid()}_{asyncio.get_event_loop().time()}.har"
    try:
        async def extract_jobs_from_page_data(data):
            prompt = build_extract_jobs_prompt(data)
            try:
                response = await request_structured_output(
                    prompt=prompt,
                    text_format=JOB_LISTINGS_RESPONSE_FORMAT,
                    max_output_tokens=6000,
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

            raw = response.output_text
            fallback = empty_job_result(
                data["final_url"],
                data["title"],
                f"AI did not return valid JSON. Raw prefix: {raw[:1000]}",
            )
            return parse_json_output(raw, fallback)

        data = await get_page_data_and_har(req.url, tmp_file)
        parsed_result = await extract_jobs_from_page_data(data)

        # --- THE AUTOMATED FALLBACK CHECK ---
        # If the extraction runs cleanly but yields empty arrays, automatically pivot to network fallback analysis
        if not parsed_result.get("jobs") or len(parsed_result["jobs"]) == 0:
            print(f"🔍 No explicit visual jobs found on {req.url}. Re-routing to HAR network pipeline...")
            traffic_logs = await get_har_entries(tmp_file)
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
