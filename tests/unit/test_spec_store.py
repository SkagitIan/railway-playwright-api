import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scraper.ats.spec_store import (
    clear_all_data,
    clear_pipeline_runs,
    demote_spec,
    get_pipeline_run,
    get_promoted_spec,
    init_db,
    list_pipeline_runs,
    promote_spec,
    save_observation,
    save_pipeline_run,
)


def test_get_promoted_spec_initializes_fresh_db(tmp_path):
    db_path = tmp_path / "fresh.sqlite3"

    assert get_promoted_spec("example.com", db_path=db_path) is None
    assert db_path.exists()


def test_save_and_promote_spec(tmp_path):
    db_path = tmp_path / "specs.sqlite3"
    init_db(db_path)
    spec = {"strategy": "BROWSER_HAR", "selector": ".job-card"}

    save_observation("example.com", spec, success=True, latency=340, error=None, db_path=db_path)
    assert get_promoted_spec("example.com", db_path=db_path) is None

    assert promote_spec("example.com", spec, db_path=db_path) is True
    promoted = get_promoted_spec("example.com", db_path=db_path)
    assert promoted == spec


def test_demote_spec(tmp_path):
    db_path = tmp_path / "specs.sqlite3"
    init_db(db_path)
    spec = {"strategy": "BROWSER_HAR", "selector": ".job-card"}

    save_observation("example.com", spec, success=True, latency=340, error=None, db_path=db_path)
    promote_spec("example.com", spec, db_path=db_path)

    assert demote_spec("example.com", spec, db_path=db_path) is True
    assert get_promoted_spec("example.com", db_path=db_path) is None


def test_save_and_list_pipeline_runs(tmp_path):
    db_path = tmp_path / "runs.sqlite3"
    init_db(db_path)
    result = {
        "request_id": "req-1",
        "url": "https://example.com/jobs",
        "domain": "example.com",
        "classification": {"strategy": "DIRECT_JSON_API", "ats": "greenhouse"},
        "validation": {"success": True, "job_count": 1, "notes": "ok"},
        "jobs": [
            {
                "title": "Engineer",
                "location": {"raw": "Remote"},
                "employment_type": "full_time",
                "job_url": "https://example.com/jobs/1",
            }
        ],
    }

    run_id = save_pipeline_run(result, duration_ms=125, db_path=db_path)
    runs = list_pipeline_runs(db_path=db_path)
    detail = get_pipeline_run(run_id, db_path=db_path)

    assert runs[0]["id"] == run_id
    assert runs[0]["success"] is True
    assert detail["jobs"][0]["title"] == "Engineer"
    assert detail["jobs"][0]["raw"]["job_url"] == "https://example.com/jobs/1"


def test_clear_helpers(tmp_path):
    db_path = tmp_path / "clear.sqlite3"
    init_db(db_path)
    spec = {"strategy": "BROWSER_HAR", "selector": ".job-card"}
    save_observation("example.com", spec, success=True, latency=340, error=None, db_path=db_path)
    save_pipeline_run(
        {
            "request_id": "req-1",
            "url": "https://example.com/jobs",
            "domain": "example.com",
            "classification": {},
            "validation": {"success": True, "job_count": 1, "notes": "ok"},
            "jobs": [{"title": "Engineer"}],
        },
        db_path=db_path,
    )

    assert clear_pipeline_runs(db_path=db_path) == {"runs": 1, "jobs": 1}
    assert list_pipeline_runs(db_path=db_path) == []
    assert clear_all_data(db_path=db_path) == {"jobs": 0, "runs": 0, "observations": 1, "specs": 1}
