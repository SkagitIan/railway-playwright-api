"""Stage 2: acquire raw data for downstream extraction."""


async def run(stage_input: dict) -> dict:
    """Normalize raw acquisition output shape.

    This is intentionally simple while the pipeline modules are being split out.
    """
    classification = stage_input["classification"]

    raw_data = {
        "source_url": stage_input["url"],
        "data_type": "json" if classification["strategy"] == "DIRECT_JSON_API" else "html",
        "text": None,
        "container_html": None,
        "links": [],
        "json_body": None,
        "har_entries": [],
        "pages_scraped": 0,
    }

    return {**stage_input, "raw_data": raw_data}
