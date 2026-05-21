"""Playwright context lifecycle helpers."""

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

from scraper.config import BROWSER_CONTEXT_OPTIONS, BROWSER_GOTO_TIMEOUT_MS

_CF_CHALLENGE_TITLES = {"just a moment...", "please wait...", "checking your browser"}


async def _wait_past_cf_challenge(page, timeout_ms: int = 15000) -> None:
    """If Cloudflare's JS challenge landed, wait up to timeout_ms for it to resolve."""
    try:
        title = (await page.title()).lower()
    except Exception:
        return
    if title not in _CF_CHALLENGE_TITLES:
        return
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass  # best-effort — scrape whatever rendered


async def fetch_page_with_context(url: str, har_path: str | None = None):
    """Open a stealth page with shared browser defaults and return resources for callers.

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

    # Must apply stealth before any navigation so JS patches are in place
    await stealth_async(page)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_GOTO_TIMEOUT_MS)
    except Exception:
        await page.goto(url, wait_until="load", timeout=BROWSER_GOTO_TIMEOUT_MS)

    await _wait_past_cf_challenge(page)

    return playwright, browser, context, page
