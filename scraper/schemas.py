JOB_LISTINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "source_url": {"type": "string", "description": "The final rendered URL used as the source for extraction."},
        "page_title": {"type": ["string", "null"], "description": "The page title, if available."},
        "company_name": {"type": ["string", "null"], "description": "The company or organization hiring for the roles, if known."},
        "jobs": {
            "type": "array",
            "description": "Real job listings found on the page. Exclude navigation, generic careers copy, and non-job links.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The job title exactly as shown or clearly implied."},
                    "company_name": {"type": ["string", "null"], "description": "The hiring company for this listing, if different or explicitly shown."},
                    "department": {"type": ["string", "null"], "description": "Department, team, or job family."},
                    "employment_type": {
                        "type": ["string", "null"],
                        "description": "Employment type when stated.",
                        "enum": ["full_time", "part_time", "contract", "temporary", "internship", "volunteer", "per_diem", "other", None],
                    },
                    "workplace_type": {
                        "type": ["string", "null"],
                        "description": "Whether the role is remote, hybrid, onsite, or not stated.",
                        "enum": ["remote", "hybrid", "onsite", "unspecified", None],
                    },
                    "location": {
                        "type": "object",
                        "properties": {
                            "raw": {"type": ["string", "null"], "description": "Location text exactly as shown."},
                            "city": {"type": ["string", "null"], "description": "City, if identifiable."},
                            "region": {"type": ["string", "null"], "description": "State, province, or region, if identifiable."},
                            "country": {"type": ["string", "null"], "description": "Country, if identifiable."},
                        },
                        "required": ["raw", "city", "region", "country"],
                        "additionalProperties": False,
                    },
                    "additional_locations": {
                        "type": "array",
                        "description": "Additional listed locations, normalized only when clearly present.",
                        "items": {"type": "string"},
                    },
                    "job_url": {"type": ["string", "null"], "description": "Best URL for the job detail page."},
                    "apply_url": {"type": ["string", "null"], "description": "Best URL for directly applying, if different from job_url."},
                    "posted_date": {"type": ["string", "null"], "description": "Posting date as shown or ISO-like if directly inferable."},
                    "closing_date": {"type": ["string", "null"], "description": "Application deadline or closing date, if shown."},
                    "compensation": {
                        "type": "object",
                        "properties": {
                            "raw": {"type": ["string", "null"], "description": "Compensation text exactly as shown."},
                            "currency": {"type": ["string", "null"], "description": "Currency code or symbol when shown."},
                            "min_amount": {"type": ["number", "null"], "description": "Minimum pay amount, if stated."},
                            "max_amount": {"type": ["number", "null"], "description": "Maximum pay amount, if stated."},
                            "period": {
                                "type": ["string", "null"],
                                "description": "Pay period when stated.",
                                "enum": ["hourly", "daily", "weekly", "monthly", "yearly", "contract", "other", None],
                            },
                        },
                        "required": ["raw", "currency", "min_amount", "max_amount", "period"],
                        "additionalProperties": False,
                    },
                    "experience_level": {
                        "type": ["string", "null"],
                        "description": "Seniority or experience level when stated or clearly implied.",
                        "enum": ["intern", "entry", "mid", "senior", "lead", "manager", "director", "executive", "unspecified", None],
                    },
                    "description": {"type": ["string", "null"], "description": "Short description or summary of the role."},
                    "responsibilities": {"type": "array", "description": "Responsibilities explicitly listed or clearly summarized from the listing.", "items": {"type": "string"}},
                    "qualifications": {"type": "array", "description": "Requirements or qualifications explicitly listed or clearly summarized.", "items": {"type": "string"}},
                    "benefits": {"type": "array", "description": "Benefits explicitly listed for this role.", "items": {"type": "string"}},
                    "skills": {"type": "array", "description": "Skills, tools, technologies, licenses, or certifications mentioned.", "items": {"type": "string"}},
                    "source_link_text": {"type": ["string", "null"], "description": "Anchor text from the matching link, if a link identified the job."},
                    "evidence": {"type": ["string", "null"], "description": "Brief source text that supports this as a real job listing."},
                    "confidence": {"type": "number", "description": "Extractor confidence from 0 to 100."},
                },
                "required": [
                    "title", "company_name", "department", "employment_type", "workplace_type", "location",
                    "additional_locations", "job_url", "apply_url", "posted_date", "closing_date", "compensation",
                    "experience_level", "description", "responsibilities", "qualifications", "benefits", "skills",
                    "source_link_text", "evidence", "confidence"
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": ["string", "null"], "description": "Short extraction notes, especially if no jobs were found."},
    },
    "required": ["source_url", "page_title", "company_name", "jobs", "notes"],
    "additionalProperties": False,
}

JOB_LISTINGS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "job_listings",
    "description": "Structured extraction result for job listings on a rendered web page.",
    "strict": True,
    "schema": JOB_LISTINGS_SCHEMA,
}

SCRAPER_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "data_delivery_type": {"type": "string", "description": "Classification of how job data is delivered.", "enum": ["json_api", "html_page", "html_fragment", "unknown"]},
        "requires_browser": {"type": "boolean", "description": "True if the page must be rendered in a browser."},
        "browser_target_url": {"type": ["string", "null"], "description": "Best renderable jobs/careers page URL when no reproducible JSON API endpoint is available."},
        "api_target_url": {"type": ["string", "null"], "description": "Discovered JSON API URL, if one exists."},
        "method": {"type": "string", "description": "HTTP method required to fetch the job list endpoint.", "enum": ["GET", "POST", "NONE"]},
        "required_headers": {
            "type": "object",
            "properties": {
                "accept": {"type": ["string", "null"]},
                "content_type": {"type": ["string", "null"]},
                "authorization": {"type": ["string", "null"]},
                "user_agent": {"type": ["string", "null"]},
                "referer": {"type": ["string", "null"]},
            },
            "required": ["accept", "content_type", "authorization", "user_agent", "referer"],
            "additionalProperties": False,
        },
        "payload": {"type": ["string", "null"], "description": "POST body or query payload, if needed."},
        "json_path_to_listings": {"type": ["string", "null"], "description": "Path to the listings array in the JSON response."},
        "explanation": {"type": "string", "description": "Brief explanation of the scrape route."},
    },
    "required": ["data_delivery_type", "requires_browser", "browser_target_url", "api_target_url", "method", "required_headers", "payload", "json_path_to_listings", "explanation"],
    "additionalProperties": False,
}

SCRAPER_SPEC_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "scraper_specification",
    "description": "An execution spec mapping an internal ATS or company XHR request footprint to duplicate dynamically.",
    "strict": True,
    "schema": SCRAPER_SPEC_SCHEMA,
}

DISCOVERY_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "source_url": {"type": ["string", "null"], "description": "Best URL that lists this employer's open jobs."},
        "source_type": {
            "type": "string",
            "description": "Kind of source found.",
            "enum": ["company_careers", "ats", "third_party", "not_found"],
        },
        "confidence": {"type": "number", "description": "Confidence from 0 to 100."},
        "reason": {"type": "string", "description": "Brief explanation for the URL choice."},
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLs used as evidence.",
        },
    },
    "required": ["source_url", "source_type", "confidence", "reason", "citations"],
    "additionalProperties": False,
}

DISCOVERY_SOURCE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "discovery_source",
    "description": "Best jobs or careers source URL for a discovered business.",
    "strict": True,
    "schema": DISCOVERY_SOURCE_SCHEMA,
}

DISCOVERY_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "industry_fit": {
            "type": "string",
            "description": "Whether the business belongs in the selected discovery industry.",
            "enum": ["match", "maybe", "no_match"],
        },
        "confidence": {"type": "number", "description": "Classification confidence from 0 to 100."},
        "reason": {"type": "string", "description": "Short explanation based only on provided metadata."},
        "suggested_industry": {
            "type": ["string", "null"],
            "description": "A better preset industry if this business appears miscategorized.",
        },
        "signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short positive or negative metadata signals used for the decision.",
        },
        "reject_reason": {
            "type": ["string", "null"],
            "description": "Short reason when industry_fit is no_match; otherwise null.",
        },
    },
    "required": ["industry_fit", "confidence", "reason", "suggested_industry", "signals", "reject_reason"],
    "additionalProperties": False,
}

DISCOVERY_CLASSIFICATION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "discovery_classification",
    "description": "Industry fit classification for a Google Places discovery candidate.",
    "strict": True,
    "schema": DISCOVERY_CLASSIFICATION_SCHEMA,
}
