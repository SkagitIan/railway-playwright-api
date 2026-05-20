import json
import os
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import Field
from playwright.async_api import async_playwright
from openai import APITimeoutError, OpenAI
from scraper.config import AI_MODEL, AI_TIMEOUT_SECONDS
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


async def _interact_with_page(page):
    # Try to expose lazy-loaded listings with a short, simple scroll pass.
    await page.wait_for_timeout(2000)
    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(750)

    # Click common "load more jobs" controls if present.
    for selector in [
        "button:has-text('Load more')",
        "button:has-text('Show more')",
        "button:has-text('View more')",
        "a:has-text('Load more')",
        "a:has-text('Show more')",
        "a:has-text('View more')",
    ]:
        try:
            target = page.locator(selector).first
            if await target.count() > 0:
                await target.click(timeout=2000)
                await page.wait_for_timeout(1500)
        except Exception:
            pass

async def collect_paginated_page_data(page, max_pages=5):
    pages = []

    for page_num in range(max_pages):
        await _interact_with_page(page)

        text = await page.locator("body").inner_text()
        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({
                text: (a.innerText || '').trim(),
                href: a.href
            })).filter(x => x.href)"""
        )

        pages.append({
            "page_num": page_num + 1,
            "url": page.url,
            "text": text,
            "links": links,
        })

        clicked = False

        for selector in [
            "a[aria-label='Next']",
            "button[aria-label='Next']",
            "a:has-text('Next')",
            "button:has-text('Next')",
            ".pagination a:has-text('Next')",
            "li.next a",
        ]:
            try:
                next_button = page.locator(selector).first
                if await next_button.count() > 0 and await next_button.is_enabled():
                    await next_button.click(timeout=3000)
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1500)
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            break

    return pages
    
async def get_page_data_and_har(url: str, har_path: str | None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context_options = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "viewport": {"width": 1366, "height": 768},
            "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        }
        if har_path:
            context_options["record_har_path"] = har_path
            context_options["record_har_mode"] = "full"

        context = await browser.new_context(
            **context_options
        )

        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            await page.goto(url, wait_until="load", timeout=60000)

        title = await page.title()
        pages = await collect_paginated_page_data(page, max_pages=8)
        
        final_url = page.url
        
        text = "\n\n--- PAGE BREAK ---\n\n".join(
            p["text"] for p in pages
        )
        
        links = []
        seen = set()
        
        for p in pages:
            for link in p["links"]:
                key = (link["text"], link["href"])
                if key not in seen:
                    seen.add(key)
                    links.append(link)
        await context.close()
        await browser.close()

        return {
            "url": url,
            "final_url": final_url,
            "title": title,
            "text": text,
            "links": links,
            "pages_scraped": len(pages),
        }
# --- Core Logic for Processing HAR Network Records ---

async def get_har_entries(tmp_har_file: str):
    """
    Spins up Playwright to navigate a page while actively archiving network streams into a local HAR archive file,
    then processes that HAR data into a condensed, token-safe log payload.
    """
    # Read and sanitize the generated HAR archive
    if not os.path.exists(tmp_har_file):
        return []

    with open(tmp_har_file, 'r', encoding='utf-8', errors='ignore') as f:
        har_data = json.load(f)

    filtered_entries = []
    for entry in har_data.get('log', {}).get('entries', []):
        request = entry.get('request', {})
        response = entry.get('response', {})
        url_str = request.get('url', '')
        
        # Pull mime/resource indicators
        mime_type = response.get('content', {}).get('mimeType', '').lower()
        resource_type = entry.get('_resourceType', '').lower()

        # Skip typical performance tracking & asset weight bloat
        ignored_domains = ['google-analytics', 'doubleclick', 'facebook', 'hotjar', 'intercom', 'sentry', 'mixpanel']
        if any(domain in url_str for domain in ignored_domains):
            continue

        # Keep document requests or programmatic async requests (fetch/xhr)
        is_async = resource_type in ['fetch', 'xhr']
        is_api = any(x in mime_type for x in ['json', 'xml'])
        is_html = 'text/html' in mime_type

        if is_api or is_html:
            body_text = response.get('content', {}).get('text', '') or ''
            
            # Trim massive structural responses down to token-safe limits
            if len(body_text) > 8000:
                body_text = body_text[:8000] + "\n... [Truncated for brevity] ..."

            filtered_entries.append({
                "url": url_str,
                "method": request.get('method'),
                "status": response.get('status'),
                "resource_type": resource_type or mime_type,
                "is_async_request": is_async,
                "important_headers": {
                    h['name']: h['value'] for h in request.get('headers', []) 
                    if h['name'].lower() in ['accept', 'content-type', 'authorization', 'referer', 'user-agent']
                },
                "response_body_snippet": body_text
            })

    # Cleanup local tracking file safely
    try:
        os.remove(tmp_har_file)
    except OSError:
        pass

    return filtered_entries


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
