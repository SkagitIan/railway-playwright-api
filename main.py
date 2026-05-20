import json
import os
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright
from openai import APITimeoutError, OpenAI

app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
AI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "510"))

# --- Existing Schema Configurations ---

JOB_LISTINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "source_url": {"type": "string", "description": "The final rendered URL used as the source for extraction."},
        "page_title": {"type": ["string", "null"], "description": "The page title, if available."},
        "company_name": {"type": ["string", "null"], "description": "The company or organization hiring for the roles, if known."},
        "jobs": {
            "type": "array",
            "description": "Real job listings found on the page. Exclude navigation, generic careers copy, and non-job links.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The job title exactly as shown or clearly implied."},
                    "company_name": {"type": ["string", "null"], "description": "The hiring company for this listing, if different or explicitly shown."},
                    "department": {"type": ["string", "null"], "description": "Department, team, or job family."},
                    "employment_type": {
                        "type": ["string", "null"],
                        "description": "Employment type when stated.",
                        "enum": ["full_time", "part_time", "contract", "temporary", "internship", "volunteer", "per_diem", "other", None],
                    },
                    "workplace_type": {
                        "type": ["string", "null"],
                        "description": "Whether the role is remote, hybrid, onsite, or not stated.",
                        "enum": ["remote", "hybrid", "onsite", "unspecified", None],
                    },
                    "location": {
                        "type": "object",
                        "properties": {
                            "raw": {"type": ["string", "null"], "description": "Location text exactly as shown."},
                            "city": {"type": ["string", "null"], "description": "City, if identifiable."},
                            "region": {"type": ["string", "null"], "description": "State, province, or region, if identifiable."},
                            "country": {"type": ["string", "null"], "description": "Country, if identifiable."},
                        },
                        "required": ["raw", "city", "region", "country"],
                        "additionalProperties": False,
                    },
                    "additional_locations": {
                        "type": "array",
                        "description": "Additional listed locations, normalized only when clearly present.",
                        "items": {"type": "string"},
                    },
                    "job_url": {"type": ["string", "null"], "description": "Best URL for the job detail page."},
                    "apply_url": {"type": ["string", "null"], "description": "Best URL for directly applying, if different from job_url."},
                    "posted_date": {"type": ["string", "null"], "description": "Posting date as shown or ISO-like if directly inferable."},
                    "closing_date": {"type": ["string", "null"], "description": "Application deadline or closing date, if shown."},
                    "compensation": {
                        "type": "object",
                        "properties": {
                            "raw": {"type": ["string", "null"], "description": "Compensation text exactly as shown."},
                            "currency": {"type": ["string", "null"], "description": "Currency code or symbol when shown."},
                            "min_amount": {"type": ["number", "null"], "description": "Minimum pay amount, if stated."},
                            "max_amount": {"type": ["number", "null"], "description": "Maximum pay amount, if stated."},
                            "period": {
                                "type": ["string", "null"],
                                "description": "Pay period when stated.",
                                "enum": ["hourly", "daily", "weekly", "monthly", "yearly", "contract", "other", None],
                            },
                        },
                        "required": ["raw", "currency", "min_amount", "max_amount", "period"],
                        "additionalProperties": False,
                    },
                    "experience_level": {
                        "type": ["string", "null"],
                        "description": "Seniority or experience level when stated or clearly implied.",
                        "enum": ["intern", "entry", "mid", "senior", "lead", "manager", "director", "executive", "unspecified", None],
                    },
                    "description": {"type": ["string", "null"], "description": "Short description or summary of the role."},
                    "responsibilities": {"type": "array", "description": "Responsibilities explicitly listed or clearly summarized from the listing.", "items": {"type": "string"}},
                    "qualifications": {"type": "array", "description": "Requirements or qualifications explicitly listed or clearly summarized.", "items": {"type": "string"}},
                    "benefits": {"type": "array", "description": "Benefits explicitly listed for this role.", "items": {"type": "string"}},
                    "skills": {"type": "array", "description": "Skills, tools, technologies, licenses, or certifications mentioned.", "items": {"type": "string"}},
                    "source_link_text": {"type": ["string", "null"], "description": "Anchor text from the matching link, if a link identified the job."},
                    "evidence": {"type": ["string", "null"], "description": "Brief source text that supports this as a real job listing."},
                    "confidence": {"type": "number", "description": "Extractor confidence from 0 to 100."},
                },
                "required": [
                    "title", "company_name", "department", "employment_type", "workplace_type", "location",
                    "additional_locations", "job_url", "apply_url", "posted_date", "closing_date", "compensation",
                    "experience_level", "description", "responsibilities", "qualifications", "benefits", "skills",
                    "source_link_text", "evidence", "confidence"
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": ["string", "null"], "description": "Short extraction notes, especially if no jobs were found."},
    },
    "required": ["source_url", "page_title", "company_name", "jobs", "notes"],
    "additionalProperties": False,
}

JOB_LISTINGS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "job_listings",
    "description": "Structured extraction result for job listings on a rendered web page.",
    "strict": True,
    "schema": JOB_LISTINGS_SCHEMA,
}

# --- New Schema: Autonomous API Spec Generation ---

SCRAPER_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "data_delivery_type": {
            "type": "string",
            "description": "Classification of how job data is delivered.",
            "enum": ["json_api", "html_page", "unknown"]
        },
        "requires_browser": {
            "type": "boolean",
            "description": "True if jobs are embedded statically in HTML or rely on highly dynamic tokens that make raw API calls impossible."
        },
        "browser_target_url": {
            "type": ["string", "null"],
            "description": "Best renderable jobs/careers page URL when no reproducible JSON API endpoint is clearly available."
        },
        "api_target_url": {
            "type": ["string", "null"],
            "description": "The discovered internal API URL that handles job data payloads (e.g., Greenhouse/Lever JSON endpoints)."
        },
        "browser_target_url": {
            "type": ["string", "null"],
            "description": "Rendered browser URL used when direct API replication is not feasible."
        },
        "data_delivery_type": {
            "type": "string",
            "description": "How listing data is delivered (xhr, fetch, html_embed, unknown).",
            "enum": ["xhr", "fetch", "html_embed", "unknown"]
        },
        "method": {
            "type": "string",
            "description": "HTTP Method required to fetch the job list endpoint.",
            "enum": ["GET", "POST", "NONE"]
        },
        "required_headers": {
                "type": "object",
                "description": "Known request headers useful for duplicating the request.",
                "properties": {
                    "accept": {"type": ["string", "null"]},
                    "content_type": {"type": ["string", "null"]},
                    "authorization": {"type": ["string", "null"]},
                    "user_agent": {"type": ["string", "null"]},
                    "referer": {"type": ["string", "null"]}
                },
                "required": [
                    "accept",
                    "content_type",
                    "authorization",
                    "user_agent",
                    "referer"
                ],
                "additionalProperties": False
            },
        "payload": {
            "type": ["string", "null"],
            "description": "Raw string, query parameters, or JSON body payload needed if the request method is POST."
        },
        "json_path_to_listings": {
            "type": ["string", "null"],
            "description": "The target JSON map trajectory to reach the root array containing jobs (e.g., 'jobs', 'data.items', or 'root')."
        },
        "explanation": {
            "type": "string",
            "description": "Brief explanation of how this ATS delivers data based on network patterns discovered."
        },
        "browser_target_url": {
            "type": ["string", "null"],
            "description": "Best URL to render when no direct API endpoint is available."
        },
        "data_delivery_type": {
            "type": "string",
            "description": "Classification of where listings are expected.",
            "enum": ["json_api", "html_page", "unknown"]
        }
    },
    "required": ["data_delivery_type", "requires_browser", "browser_target_url", "api_target_url", "method", "required_headers", "payload", "json_path_to_listings", "explanation"],
    "additionalProperties": False
}

SCRAPER_SPEC_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "scraper_specification",
    "description": "An execution spec mapping an internal ATS or company XHR request footprint to duplicate dynamically.",
    "strict": True,
    "schema": SCRAPER_SPEC_SCHEMA,
}

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


class UrlRequest(BaseModel):
    url: str


async def get_page_data(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )

        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(5000)

        title = await page.title()
        final_url = page.url
        text = await page.locator("body").inner_text()

        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({
                text: (a.innerText || '').trim(),
                href: a.href
            })).filter(x => x.href)"""
        )

        await browser.close()

    return {
        "url": url,
        "final_url": final_url,
        "title": title,
        "text": text,
        "links": links,
    }

# --- Core Logic for Processing HAR Network Records ---

async def get_page_har_data(url: str, tmp_har_file: str):
    """
    Spins up Playwright to navigate a page while actively archiving network streams into a local HAR archive file,
    then processes that HAR data into a condensed, token-safe log payload.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            record_har_path=tmp_har_file
        )

        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass # Try reading what it gathered anyway if it times out
        finally:
            await context.close()
            await browser.close()

    # Read and sanitize the generated HAR archive immediately
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
        is_api = any(x in mime_type or x in resource_type for x in ['json', 'xml', 'fetch', 'xhr'])
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
                "important_headers": {
                    h['name']: h['value'] for h in request.get('headers', []) 
                    if h['name'].lower() in ['accept', 'content-type', 'authorization']
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
        # 1. Capture the structural network traffic logs
        traffic_logs = await get_page_har_data(req.url, tmp_file)
        
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
                "browser_target_url": None,
                "data_delivery_type": "unknown",
            }

        # 2. Package request traces into an analytical diagnosis prompt
        prompt = f"""
You are an advanced web scraping backend system routing requests for Applicant Tracking Systems (ATS).
Review the following filtered network logs captured via a browser rendering engine on a company careers page.

Classification Contract:
- Return data_delivery_type = "json_api" when a reproducible JSON endpoint exists.
- Return data_delivery_type = "html_page" when the HAR includes a likely jobs/careers HTML document suitable for browser rendering.
- Return data_delivery_type = "unknown" when neither path is clear.

Required Output Rules:
- If data_delivery_type = "json_api": set api_target_url and provide the appropriate method, required_headers, payload, and json_path_to_listings.
- If data_delivery_type = "html_page": set browser_target_url to the best renderable jobs/careers URL; set api_target_url = null and method = "NONE" unless a real API is also clearly found.
- If data_delivery_type = "unknown": use nulls/"NONE" where appropriate and explain uncertainty.
- Avoid vendor-specific assumptions in your reasoning; infer only from observable network evidence.

NETWORK LOG DATA:
{json.dumps(traffic_logs, ensure_ascii=False, indent=2)}
"""

        # 3. Call OpenAI to reverse engineer the request footprint
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

    except asyncio.TimeoutError:
        return default_scraper_spec("Network reverse engineering request timed out.")
    except Exception as e:
        return default_scraper_spec(f"Network fallback failed safely: {str(e)}")


@app.post("/extract-jobs-ai")
async def extract_jobs_ai(req: UrlRequest):
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

        data = await get_page_data(req.url)
        parsed_result = await extract_jobs_from_page_data(data)

        # --- THE AUTOMATED FALLBACK CHECK ---
        # If the extraction runs cleanly but yields empty arrays, automatically pivot to network fallback analysis
        if not parsed_result.get("jobs") or len(parsed_result["jobs"]) == 0:
            print(f"🔍 No explicit visual jobs found on {req.url}. Re-routing to HAR network pipeline...")
            fallback_spec = await analyze_network_fallback(req)

            if (
                fallback_spec.get("data_delivery_type") == "html_page"
                and fallback_spec.get("browser_target_url")
            ):
                second_pass_url = fallback_spec["browser_target_url"]
                second_pass_data = await get_page_data(second_pass_url)
                second_pass_result = await extract_jobs_from_page_data(second_pass_data)
                second_pass_result["network_fallback_spec"] = fallback_spec
                second_pass_result["notes"] = (
                    (second_pass_result.get("notes") or "")
                    + f" [Second-pass extraction from fallback HTML source: {second_pass_url}]"
                )
                return second_pass_result

            parsed_result["network_fallback_spec"] = fallback_spec
            parsed_result["notes"] = (parsed_result.get("notes") or "") + " [Fallback Analysis Appended]"

        return parsed_result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
