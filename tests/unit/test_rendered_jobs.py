from scraper.extractors.rendered_jobs import extract_jobs_from_rendered_board


def test_extracts_generic_rendered_job_links():
    raw_data = {
        "text": "Open roles\nSenior Engineer\nRemote\nProduct Manager\nAustin, TX",
        "links": [
            {"text": "Senior Engineer", "href": "https://jobs.example.com/jobs/1"},
            {"text": "Product Manager", "href": "https://jobs.example.com/positions/2"},
        ],
    }

    jobs = extract_jobs_from_rendered_board(raw_data)

    assert [job["title"] for job in jobs] == ["Senior Engineer", "Product Manager"]
    assert jobs[0]["job_url"] == "https://jobs.example.com/jobs/1"


def test_extracts_rippling_links_without_ai():
    raw_data = {
        "text": "Manufacturing Technician\nManufacturing\nMount Vernon, WA\nProcess Engineer\nEngineering\nRemote",
        "links": [
            {"text": "Manufacturing Technician", "href": "https://ats.rippling.com/example/jobs/abc"},
            {"text": "Process Engineer", "href": "https://ats.us1.rippling.com/example/jobs/def"},
        ],
    }

    jobs = extract_jobs_from_rendered_board(raw_data)

    assert [job["title"] for job in jobs] == ["Manufacturing Technician", "Process Engineer"]
    assert jobs[0]["department"] == "Manufacturing"
    assert jobs[0]["location"] == {"raw": "Mount Vernon, WA", "city": "Mount Vernon", "region": "WA", "country": "US"}


def test_ignores_marketing_nav_and_dedupes():
    raw_data = {
        "text": "Careers\nPrivacy Policy\nSenior Engineer",
        "links": [
            {"text": "Careers", "href": "https://example.com/jobs"},
            {"text": "Privacy Policy", "href": "https://example.com/jobs/privacy"},
            {"text": "Senior Engineer", "href": "https://example.com/jobs/1"},
            {"text": "Senior Engineer", "href": "https://example.com/jobs/1"},
        ],
    }

    jobs = extract_jobs_from_rendered_board(raw_data)

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Senior Engineer"
