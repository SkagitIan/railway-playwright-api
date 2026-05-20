"""Parsing helpers for AI responses."""

from __future__ import annotations

import json


def response_refusal(response) -> str | None:
    """Return refusal text when model refuses."""
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", None) or "AI refused to extract the page."
    return None


def parse_json_output(output_text: str, fallback: dict) -> dict:
    """Parse JSON response text or return fallback payload."""
    try:
        return json.loads(output_text.strip())
    except json.JSONDecodeError:
        return fallback
