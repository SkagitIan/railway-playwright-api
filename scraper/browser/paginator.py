"""Pagination and page interaction helpers."""

from scraper.config import BROWSER_MAX_PAGES

LOAD_MORE_SELECTORS = [
    "button:has-text('Load more')",
    "button:has-text('Show more')",
    "button:has-text('View more')",
    "a:has-text('Load more')",
    "a:has-text('Show more')",
    "a:has-text('View more')",
]

NEXT_PAGE_SELECTORS = [
    "a[aria-label='Next']",
    "button[aria-label='Next']",
    "a:has-text('Next')",
    "button:has-text('Next')",
    ".pagination a:has-text('Next')",
    "li.next a",
]


async def interact_with_page(page):
    await page.wait_for_timeout(2000)
    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(750)

    for selector in LOAD_MORE_SELECTORS:
        try:
            target = page.locator(selector).first
            if await target.count() > 0:
                await target.click(timeout=2000)
                await page.wait_for_timeout(1500)
        except Exception:
            continue


async def collect_paginated_page_data(page, max_pages: int = BROWSER_MAX_PAGES):
    pages = []
    for page_num in range(max_pages):
        await interact_with_page(page)

        text = await page.locator("body").inner_text()
        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({ text: (a.innerText || '').trim(), href: a.href })).filter(x => x.href)""",
        )

        pages.append({"page_num": page_num + 1, "url": page.url, "text": text, "links": links})

        clicked = False
        for selector in NEXT_PAGE_SELECTORS:
            try:
                next_button = page.locator(selector).first
                if await next_button.count() > 0 and await next_button.is_enabled():
                    await next_button.click(timeout=3000)
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1500)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            break

    return pages
