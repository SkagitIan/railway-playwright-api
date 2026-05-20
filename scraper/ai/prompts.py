"""Prompt templates for scraper AI flows."""

from __future__ import annotations

import json


def build_network_fallback_prompt(traffic_logs: list[dict]) -> str:
    """Prompt for HAR/network analysis fallback."""
    return f"""
You are an advanced web scraping backend system routing requests for Applicant Tracking Systems (ATS).
Review the following filtered network logs captured via a browser rendering engine on a company careers page.

Classification Contract:
- Return data_delivery_type = "json_api" when a reproducible JSON endpoint exists.
- Return data_delivery_type = "html_page" when the HAR includes a likely jobs/careers HTML document suitable for browser rendering.
- Return data_delivery_type = "html_fragment" when async fetch/xhr requests return text/html fragments containing job listings.
- Return data_delivery_type = "unknown" when neither path is clear.

Required Output Rules:
- If data_delivery_type = "json_api": set api_target_url and provide the appropriate method, required_headers, payload, and json_path_to_listings.
- If data_delivery_type = "html_page": set browser_target_url to the best renderable jobs/careers URL; set api_target_url = null and method = "NONE" unless a real API is also clearly found.
- If data_delivery_type = "html_fragment": set api_target_url to that async endpoint and keep requires_browser=true if cookies/challenges are likely required.
- If data_delivery_type = "unknown": use nulls/"NONE" where appropriate and explain uncertainty.
- Avoid vendor-specific assumptions in your reasoning; infer only from observable network evidence.

NETWORK LOG DATA:
{json.dumps(traffic_logs, ensure_ascii=False, indent=2)}
"""


def build_extract_jobs_prompt(data: dict) -> str:
    """Prompt for extracting jobs from rendered page data."""
    return f"""
Extract job listings from this rendered careers/job page.

Rules:
- Only include real job listings.
- Exclude navigation links, generic career content, and unrelated pages.
- Use null for unknown scalar values.
- Use empty arrays when no list items are known.
- Prefer exact URLs from LINKS for job_url and apply_url.
- source_url must be: {data['final_url']}
- confidence is 0-100.

PAGE TITLE:
{data['title']}

VISIBLE TEXT:
{data['text']}

LINKS:
{json.dumps(data['links'], ensure_ascii=False)}
"""
