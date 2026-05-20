"""HAR parsing helpers."""

import json
import os

IGNORED_DOMAINS = ["google-analytics", "doubleclick", "facebook", "hotjar", "intercom", "sentry", "mixpanel"]
REQUEST_HEADERS = ["accept", "content-type", "authorization", "referer", "user-agent"]


def parse_har_entries(tmp_har_file: str):
    if not os.path.exists(tmp_har_file):
        return []

    with open(tmp_har_file, "r", encoding="utf-8", errors="ignore") as f:
        har_data = json.load(f)

    filtered_entries = []
    for entry in har_data.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        response = entry.get("response", {})
        url_str = request.get("url", "")

        if any(domain in url_str for domain in IGNORED_DOMAINS):
            continue

        mime_type = response.get("content", {}).get("mimeType", "").lower()
        resource_type = entry.get("_resourceType", "").lower()

        is_async = resource_type in ["fetch", "xhr"]
        is_api = any(x in mime_type for x in ["json", "xml"])
        is_html = "text/html" in mime_type

        if is_api or is_html:
            body_text = response.get("content", {}).get("text", "") or ""
            if len(body_text) > 8000:
                body_text = body_text[:8000] + "\n... [Truncated for brevity] ..."

            filtered_entries.append(
                {
                    "url": url_str,
                    "method": request.get("method"),
                    "status": response.get("status"),
                    "resource_type": resource_type or mime_type,
                    "is_async_request": is_async,
                    "important_headers": {
                        h["name"]: h["value"]
                        for h in request.get("headers", [])
                        if h["name"].lower() in REQUEST_HEADERS
                    },
                    "response_body_snippet": body_text,
                }
            )

    try:
        os.remove(tmp_har_file)
    except OSError:
        pass

    return filtered_entries
