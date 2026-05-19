import json
import os
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from openai import APITimeoutError, OpenAI

app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
AI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "510"))


JOB_LISTINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "source_url": {
            "type": "string",
            "description": "The final rendered URL used as the source for extraction.",
        },
        "page_title": {
            "type": ["string", "null"],
            "description": "The page title, if available.",
        },
        "company_name": {
            "type": ["string", "null"],
            "description": "The company or organization hiring for the roles, if known.",
        },
        "jobs": {
            "type": "array",
            "description": "Real job listings found on the page. Exclude navigation, generic careers copy, and non-job links.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The job title exactly as shown or clearly implied.",
                    },
                    "company_name": {
                        "type": ["string", "null"],
                        "description": "The hiring company for this listing, if different or explicitly shown.",
                    },
                    "department": {
                        "type": ["string", "null"],
                        "description": "Department, team, or job family.",
                    },
                    "employment_type": {
                        "type": ["string", "null"],
                        "description": "Employment type when stated.",
                        "enum": [
                            "full_time",
                            "part_time",
                            "contract",
                            "temporary",
                            "internship",
                            "volunteer",
                            "per_diem",
                            "other",
                            None,
                        ],
                    },
                    "workplace_type": {
                        "type": ["string", "null"],
                        "description": "Whether the role is remote, hybrid, onsite, or not stated.",
                        "enum": ["remote", "hybrid", "onsite", "unspecified", None],
                    },
                    "location": {
                        "type": "object",
                        "properties": {
                            "raw": {
                                "type": ["string", "null"],
                                "description": "Location text exactly as shown.",
                            },
                            "city": {
                                "type": ["string", "null"],
                                "description": "City, if identifiable.",
                            },
                            "region": {
                                "type": ["string", "null"],
                                "description": "State, province, or region, if identifiable.",
                            },
                            "country": {
                                "type": ["string", "null"],
                                "description": "Country, if identifiable.",
                            },
                        },
                        "required": ["raw", "city", "region", "country"],
                        "additionalProperties": False,
                    },
                    "additional_locations": {
                        "type": "array",
                        "description": "Additional listed locations, normalized only when clearly present.",
                        "items": {"type": "string"},
                    },
                    "job_url": {
                        "type": ["string", "null"],
                        "description": "Best URL for the job detail page.",
                    },
                    "apply_url": {
                        "type": ["string", "null"],
                        "description": "Best URL for directly applying, if different from job_url.",
                    },
                    "posted_date": {
                        "type": ["string", "null"],
                        "description": "Posting date as shown or ISO-like if directly inferable.",
                    },
                    "closing_date": {
                        "type": ["string", "null"],
                        "description": "Application deadline or closing date, if shown.",
                    },
                    "compensation": {
                        "type": "object",
                        "properties": {
                            "raw": {
                                "type": ["string", "null"],
                                "description": "Compensation text exactly as shown.",
                            },
                            "currency": {
                                "type": ["string", "null"],
                                "description": "Currency code or symbol when shown.",
                            },
                            "min_amount": {
                                "type": ["number", "null"],
                                "description": "Minimum pay amount, if stated.",
                            },
                            "max_amount": {
                                "type": ["number", "null"],
                                "description": "Maximum pay amount, if stated.",
                            },
                            "period": {
                                "type": ["string", "null"],
                                "description": "Pay period when stated.",
                                "enum": [
                                    "hourly",
                                    "daily",
                                    "weekly",
                                    "monthly",
                                    "yearly",
                                    "contract",
                                    "other",
                                    None,
                                ],
                            },
                        },
                        "required": ["raw", "currency", "min_amount", "max_amount", "period"],
                        "additionalProperties": False,
                    },
                    "experience_level": {
                        "type": ["string", "null"],
                        "description": "Seniority or experience level when stated or clearly implied.",
                        "enum": [
                            "intern",
                            "entry",
                            "mid",
                            "senior",
                            "lead",
                            "manager",
                            "director",
                            "executive",
                            "unspecified",
                            None,
                        ],
                    },
                    "description": {
                        "type": ["string", "null"],
                        "description": "Short description or summary of the role.",
                    },
                    "responsibilities": {
                        "type": "array",
                        "description": "Responsibilities explicitly listed or clearly summarized from the listing.",
                        "items": {"type": "string"},
                    },
                    "qualifications": {
                        "type": "array",
                        "description": "Requirements or qualifications explicitly listed or clearly summarized.",
                        "items": {"type": "string"},
                    },
                    "benefits": {
                        "type": "array",
                        "description": "Benefits explicitly listed for this role.",
                        "items": {"type": "string"},
                    },
                    "skills": {
                        "type": "array",
                        "description": "Skills, tools, technologies, licenses, or certifications mentioned.",
                        "items": {"type": "string"},
                    },
                    "source_link_text": {
                        "type": ["string", "null"],
                        "description": "Anchor text from the matching link, if a link identified the job.",
                    },
                    "evidence": {
                        "type": ["string", "null"],
                        "description": "Brief source text that supports this as a real job listing.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Extractor confidence from 0 to 100.",
                    },
                },
                "required": [
                    "title",
                    "company_name",
                    "department",
                    "employment_type",
                    "workplace_type",
                    "location",
                    "additional_locations",
                    "job_url",
                    "apply_url",
                    "posted_date",
                    "closing_date",
                    "compensation",
                    "experience_level",
                    "description",
                    "responsibilities",
                    "qualifications",
                    "benefits",
                    "skills",
                    "source_link_text",
                    "evidence",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": ["string", "null"],
            "description": "Short extraction notes, especially if no jobs were found.",
        },
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


def empty_job_result(source_url: str, page_title: str | None, notes: str):
    return {
        "source_url": source_url,
        "page_title": page_title,
        "company_name": None,
        "jobs": [],
        "notes": notes,
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


@app.post("/extract-jobs-ai")
async def extract_jobs_ai(req: UrlRequest):
    try:
        data = await get_page_data(req.url)

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
        except Exception:
            return empty_job_result(
                data["final_url"],
                data["title"],
                f"AI did not return valid JSON. Raw prefix: {raw[:1000]}",
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
