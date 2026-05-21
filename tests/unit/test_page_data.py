import asyncio

from scraper import page_data


class FakePage:
    def __init__(self):
        self.url = "https://example.com/final"
        self.title_calls = 0

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None

    async def wait_for_timeout(self, *_args, **_kwargs):
        return None

    async def title(self):
        self.title_calls += 1
        if self.title_calls == 1:
            raise Exception("Execution context was destroyed, most likely because of a navigation")
        return "Careers"


class FakeClosable:
    async def close(self):
        return None

    async def stop(self):
        return None


def test_get_page_data_retries_title_during_late_navigation(monkeypatch):
    fake_page = FakePage()

    async def fake_fetch_page_with_context(url, har_path):
        return FakeClosable(), FakeClosable(), FakeClosable(), fake_page

    async def fake_collect_paginated_page_data(page):
        return [{"text": "Senior Engineer", "links": [{"text": "Senior Engineer", "href": "https://example.com/jobs/1"}]}]

    monkeypatch.setattr(page_data, "fetch_page_with_context", fake_fetch_page_with_context)
    monkeypatch.setattr(page_data, "collect_paginated_page_data", fake_collect_paginated_page_data)

    result = asyncio.run(page_data.get_page_data_and_har("https://example.com/careers"))

    assert result["title"] == "Careers"
    assert result["pages_scraped"] == 1
    assert fake_page.title_calls == 2
