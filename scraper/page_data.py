"""Rendered page and HAR acquisition helpers shared by API versions."""

from scraper.browser.context import fetch_page_with_context
from scraper.browser.paginator import collect_paginated_page_data


async def _safe_title(page) -> str | None:
    """Read title after late client-side navigation settles."""
    last_error = None
    for _ in range(3):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            return await page.title()
        except Exception as exc:
            last_error = exc
            try:
                await page.wait_for_timeout(500)
            except Exception:
                break
    if last_error:
        print({"stage": "page_data", "warning": "title_unavailable", "reason": str(last_error)})
    return None


async def get_page_data_and_har(url: str, har_path: str | None = None) -> dict:
    playwright, browser, context, page = await fetch_page_with_context(url, har_path)
    try:
        title = await _safe_title(page)
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


async def get_page_data(url: str) -> dict:
    return await get_page_data_and_har(url, None)
