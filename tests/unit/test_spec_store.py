import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scraper.ats.spec_store import demote_spec, get_promoted_spec, init_db, promote_spec, save_observation


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
