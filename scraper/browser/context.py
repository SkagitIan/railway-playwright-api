"""Playwright context lifecycle helpers."""

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

from scraper.config import BROWSER_CONTEXT_OPTIONS, BROWSER_GOTO_TIMEOUT_MS

_CF_CHALLENGE_TITLES = {"just a moment...", "please wait...", "checking your browser"}


async def _wait_past_cf_challenge(page, timeout_ms: int = 25000) -> None:
    """If Cloudflare's JS challenge landed, wait for it to redirect to the real page.

    networkidle fires in the gap between the chl_api_m "ok" response and the
    redirect the challenge JS triggers, so we watch the title instead.
    """
    try:
        title = (await page.title()).lower()
    except Exception:
        return
    if title not in _CF_CHALLENGE_TITLES:
        return
    try:
        # Poll until the title is no longer a CF challenge title
        await page.wait_for_function(
            """() => {
                const t = document.title.toLowerCase();
                return !t.includes('just a moment') &&
                       !t.includes('please wait') &&
                       !t.includes('checking your browser');
            }""",
            timeout=timeout_ms,
        )
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
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
