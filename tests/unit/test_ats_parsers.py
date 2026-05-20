import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from scraper.ats.parsers import parse_ashby_jobs, parse_greenhouse_jobs, parse_lever_jobs


def test_greenhouse_parser_maps_fields():
    payload = {
        "jobs": [
            {
                "title": "Software Engineer",
                "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
                "location": {"name": "San Francisco, CA"},
                "departments": [{"name": "Engineering"}],
            }
        ]
    }
    jobs = parse_greenhouse_jobs(payload)
    assert jobs[0]["title"] == "Software Engineer"
    assert jobs[0]["location"] == "San Francisco, CA"
    assert jobs[0]["department"] == "Engineering"


def test_lever_parser_maps_fields():
    payload = [
        {
            "text": "Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/x/1",
            "categories": {
                "location": "Remote",
                "team": "Platform",
                "commitment": "Full-time",
            },
        }
    ]
    jobs = parse_lever_jobs(payload)
    assert jobs[0]["title"] == "Backend Engineer"
    assert jobs[0]["location"] == "Remote"
    assert jobs[0]["employment_type"] == "Full-time"


def test_ashby_parser_maps_fields():
    payload = {
        "jobPostings": [
            {
                "title": "Data Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/x/1",
                "location": {"name": "New York, NY"},
                "department": {"name": "Data"},
                "employmentType": "Full-time",
            }
        ]
    }
    jobs = parse_ashby_jobs(payload)
    assert jobs[0]["title"] == "Data Engineer"
    assert jobs[0]["location"] == "New York, NY"
    assert jobs[0]["department"] == "Data"
