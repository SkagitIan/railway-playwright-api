import json
import os

from fastapi import FastAPI
from pydantic import BaseModel
from playwright.async_api import async_playwright
from openai import OpenAI

app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


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
        "text": text[:50000],
        "links": links[:200],
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
    data = await get_page_data(req.url)

    prompt = f"""
Extract job listings from this rendered careers/job page.

Return ONLY valid JSON in this shape:

{{
  "source_url": "{data["final_url"]}",
  "jobs": [
    {{
      "title": "",
      "company": "",
      "location": "",
      "job_url": "",
      "posted_date": null,
      "confidence": 0
    }}
  ],
  "notes": ""
}}

Rules:
- Only include real job listings.
- Do not include navigation links or generic career text.
- Use null when unknown.
- confidence is 0-100.
- Prefer exact links from the links list.

PAGE TITLE:
{data["title"]}

VISIBLE TEXT:
{data["text"][:30000]}

LINKS:
{json.dumps(data["links"][:150], ensure_ascii=False)}
"""

    response = client.responses.create(
        model="gpt-5.5-mini",
        input=prompt,
    )

    raw = response.output_text.strip()

    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {
            "source_url": data["final_url"],
            "jobs": [],
            "notes": "AI did not return valid JSON",
            "raw": raw[:5000],
        }

    return parsed