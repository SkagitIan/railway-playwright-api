import os
from datetime import timedelta

AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
AI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "510"))

BROWSER_GOTO_TIMEOUT_MS = int(os.environ.get("BROWSER_GOTO_TIMEOUT_MS", "60000"))
BROWSER_MAX_PAGES = int(os.environ.get("BROWSER_MAX_PAGES", "8"))
BROWSER_MAX_CONCURRENCY = int(os.environ.get("BROWSER_MAX_CONCURRENCY", "2"))
PIPELINE_MAX_RETRIES = int(os.environ.get("PIPELINE_MAX_RETRIES", "2"))
AI_MAX_TEXT_CHARS = int(os.environ.get("AI_MAX_TEXT_CHARS", "50000"))
AI_MAX_LINKS = int(os.environ.get("AI_MAX_LINKS", "200"))
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")
GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT = int(os.environ.get("GOOGLE_PLACES_TEXT_SEARCH_MONTHLY_LIMIT", "1000"))
DISCOVERY_MAX_PAGES_PER_CITY = int(os.environ.get("DISCOVERY_MAX_PAGES_PER_CITY", "1"))
DISCOVERY_SOURCE_RESOLVE_CONCURRENCY = int(os.environ.get("DISCOVERY_SOURCE_RESOLVE_CONCURRENCY", "2"))
DISCOVERY_OPENAI_MODEL = os.environ.get("DISCOVERY_OPENAI_MODEL", AI_MODEL)
SPEC_CACHE_TTL_SECONDS = int(os.environ.get("SPEC_CACHE_TTL_SECONDS", str(int(timedelta(minutes=15).total_seconds()))))
BROWSER_CONTEXT_OPTIONS = {
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "viewport": {"width": 1366, "height": 768},
    "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
}
