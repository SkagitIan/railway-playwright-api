from fastapi import FastAPI
from pydantic import BaseModel
from playwright.async_api import async_playwright

app = FastAPI()


class UrlRequest(BaseModel):
    url: str


@app.get("/")
def home():
    return {"status": "ok"}

@app.post("/extract-page-text")
async def extract_page_text(req: UrlRequest):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )

        page = await context.new_page()
        await page.goto(req.url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(5000)

        title = await page.title()
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
        "url": req.url,
        "title": title,
        "text": text[:50000],
        "links": links[:200],
    }

@app.post("/extract-links")
async def extract_links(req: UrlRequest):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )

        page = await context.new_page()
        await page.goto(req.url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(5000)

        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({
                text: (a.innerText || '').trim(),
                href: a.href
            })).filter(x => x.href)"""
        )

        await browser.close()

    words = ["job", "jobs", "career", "careers", "employment", "hiring", "join our team"]

    likely = [
        link for link in links
        if any(word in (link["text"] + " " + link["href"]).lower() for word in words)
    ]

    return {
        "url": req.url,
        "likely_job_links": likely[:20],
        "total_links": len(links),
    }