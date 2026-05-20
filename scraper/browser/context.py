"""Playwright context lifecycle helpers."""

from playwright.async_api import async_playwright

from scraper.config import BROWSER_CONTEXT_OPTIONS, BROWSER_GOTO_TIMEOUT_MS


async def fetch_page_with_context(url: str, har_path: str | None = None):
    """Open a page with shared browser defaults and return resources for callers.

    Caller must close context and browser.
    """
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)

    context_options = dict(BROWSER_CONTEXT_OPTIONS)
    if har_path:
        context_options["record_har_path"] = har_path
        context_options["record_har_mode"] = "full"

    context = await browser.new_context(**context_options)
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_GOTO_TIMEOUT_MS)
    except Exception:
        await page.goto(url, wait_until="load", timeout=BROWSER_GOTO_TIMEOUT_MS)

    return playwright, browser, context, page
