"""Simple SQLite-backed store for learned scraping specs."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional production dependency
    psycopg = None
    dict_row = None


DEFAULT_DB_PATH = Path("data/spec_store.sqlite3")
_INITIALIZED_DB_PATHS: set[Path] = set()
_POSTGRES_INITIALIZED = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def _use_postgres(db_path: str | Path | None = None) -> bool:
    return db_path is None and bool(_database_url())


def _connect_pg():
    if psycopg is None:
        raise RuntimeError("DATABASE_URL is set but psycopg is not installed")
    return psycopg.connect(_database_url(), row_factory=dict_row)


def init_db(db_path: str | Path | None = None) -> None:
    """Create minimal tables if they do not exist."""
    global _POSTGRES_INITIALIZED
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS specs (
                    id BIGSERIAL PRIMARY KEY,
                    domain TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    promoted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id BIGSERIAL PRIMARY KEY,
                    domain TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    latency_ms INTEGER,
                    error TEXT,
                    observed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id BIGSERIAL PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    job_count INTEGER NOT NULL,
                    strategy TEXT,
                    ats TEXT,
                    notes TEXT,
                    duration_ms INTEGER,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_jobs (
                    id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
                    title TEXT,
                    location_json TEXT,
                    employment_type TEXT,
                    workplace_type TEXT,
                    compensation_json TEXT,
                    job_url TEXT,
                    apply_url TEXT,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            _migrate_postgres_core_tables(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_specs_domain_status ON specs(domain, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_domain ON observations(domain)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created_at ON pipeline_runs(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_jobs_run_id ON saved_jobs(run_id)")
        from scraper.discovery_store import init_discovery_tables
        init_discovery_tables(db_path)
        _POSTGRES_INITIALIZED = True
        return

    path = Path(db_path or DEFAULT_DB_PATH)
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS specs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                score REAL NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                last_failure_at TEXT,
                promoted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                success INTEGER NOT NULL,
                latency_ms INTEGER,
                error TEXT,
                observed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                url TEXT NOT NULL,
                domain TEXT NOT NULL,
                success INTEGER NOT NULL,
                job_count INTEGER NOT NULL,
                strategy TEXT,
                ats TEXT,
                notes TEXT,
                duration_ms INTEGER,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                title TEXT,
                location_json TEXT,
                employment_type TEXT,
                workplace_type TEXT,
                compensation_json TEXT,
                job_url TEXT,
                apply_url TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES pipeline_runs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_specs_domain_status ON specs(domain, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_domain ON observations(domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created_at ON pipeline_runs(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_jobs_run_id ON saved_jobs(run_id)")
    from scraper.discovery_store import init_discovery_tables
    init_discovery_tables(path)
    _INITIALIZED_DB_PATHS.add(path.resolve())


def _migrate_postgres_core_tables(conn) -> None:
    now = _utc_now()
    for column, definition in {
        "domain": "TEXT",
        "spec_json": "TEXT",
        "status": "TEXT DEFAULT 'candidate'",
        "score": "DOUBLE PRECISION DEFAULT 0",
        "success_count": "INTEGER DEFAULT 0",
        "failure_count": "INTEGER DEFAULT 0",
        "last_success_at": "TEXT",
        "last_failure_at": "TEXT",
        "promoted_at": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        conn.execute(f"ALTER TABLE specs ADD COLUMN IF NOT EXISTS {column} {definition}")
    conn.execute(
        "UPDATE specs SET created_at = COALESCE(created_at, %s), updated_at = COALESCE(updated_at, %s)",
        (now, now),
    )

    for column, definition in {
        "domain": "TEXT",
        "spec_json": "TEXT",
        "success": "INTEGER DEFAULT 0",
        "latency_ms": "INTEGER",
        "error": "TEXT",
        "observed_at": "TEXT",
    }.items():
        conn.execute(f"ALTER TABLE observations ADD COLUMN IF NOT EXISTS {column} {definition}")
    conn.execute("UPDATE observations SET observed_at = COALESCE(observed_at, %s)", (now,))

    for column, definition in {
        "request_id": "TEXT",
        "url": "TEXT",
        "domain": "TEXT",
        "success": "INTEGER DEFAULT 0",
        "job_count": "INTEGER DEFAULT 0",
        "strategy": "TEXT",
        "ats": "TEXT",
        "notes": "TEXT",
        "duration_ms": "INTEGER",
        "response_json": "TEXT",
        "created_at": "TEXT",
    }.items():
        conn.execute(f"ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS {column} {definition}")
    conn.execute("UPDATE pipeline_runs SET created_at = COALESCE(created_at, %s)", (now,))

    for column, definition in {
        "run_id": "BIGINT",
        "title": "TEXT",
        "location_json": "TEXT",
        "employment_type": "TEXT",
        "workplace_type": "TEXT",
        "compensation_json": "TEXT",
        "job_url": "TEXT",
        "apply_url": "TEXT",
        "raw_json": "TEXT",
        "created_at": "TEXT",
    }.items():
        conn.execute(f"ALTER TABLE saved_jobs ADD COLUMN IF NOT EXISTS {column} {definition}")
    conn.execute("UPDATE saved_jobs SET created_at = COALESCE(created_at, %s)", (now,))


def ensure_db_initialized(db_path: str | Path | None = None) -> None:
    """Initialize the spec store once per process."""
    if _use_postgres(db_path):
        global _POSTGRES_INITIALIZED
        if not _POSTGRES_INITIALIZED:
            init_db()
        return

    path = Path(db_path or DEFAULT_DB_PATH).resolve()
    if path not in _INITIALIZED_DB_PATHS:
        init_db(path)


def get_promoted_spec(domain: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Return latest promoted spec for a domain."""
    ensure_db_initialized(db_path)
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            row = conn.execute(
                """
                SELECT spec_json FROM specs
                WHERE domain = %s AND status = 'promoted'
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (domain.lower(),),
            ).fetchone()
        return json.loads(row["spec_json"]) if row else None

    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT spec_json FROM specs
            WHERE domain = ? AND status = 'promoted'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (domain.lower(),),
        ).fetchone()
    return json.loads(row["spec_json"]) if row else None


def save_observation(
    domain: str,
    spec: dict[str, Any],
    success: bool,
    latency: int | None,
    error: str | None,
    db_path: str | Path | None = None,
) -> None:
    """Persist run outcomes and update aggregate counters for the matching spec."""
    ensure_db_initialized(db_path)
    normalized_domain = domain.lower()
    spec_json = json.dumps(spec, sort_keys=True)
    now = _utc_now()

    if _use_postgres(db_path):
        with _connect_pg() as conn:
            conn.execute(
                """
                INSERT INTO observations(domain, spec_json, success, latency_ms, error, observed_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (normalized_domain, spec_json, int(success), latency, error, now),
            )
            existing = conn.execute(
                "SELECT id, success_count, failure_count FROM specs WHERE domain = %s AND spec_json = %s LIMIT 1",
                (normalized_domain, spec_json),
            ).fetchone()
            if existing:
                success_count = existing["success_count"] + int(success)
                failure_count = existing["failure_count"] + int(not success)
                score = success_count - failure_count
                conn.execute(
                    """
                    UPDATE specs
                    SET success_count = %s, failure_count = %s, score = %s,
                        last_success_at = CASE WHEN %s = 1 THEN %s ELSE last_success_at END,
                        last_failure_at = CASE WHEN %s = 0 THEN %s ELSE last_failure_at END,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        success_count,
                        failure_count,
                        score,
                        int(success),
                        now,
                        int(success),
                        now,
                        now,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO specs(
                        domain, spec_json, status, score, success_count, failure_count,
                        last_success_at, last_failure_at, created_at, updated_at
                    )
                    VALUES (%s, %s, 'candidate', %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        normalized_domain,
                        spec_json,
                        1 if success else -1,
                        int(success),
                        int(not success),
                        now if success else None,
                        None if success else now,
                        now,
                        now,
                    ),
                )
        return

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO observations(domain, spec_json, success, latency_ms, error, observed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalized_domain, spec_json, int(success), latency, error, now),
        )

        existing = conn.execute(
            "SELECT id, success_count, failure_count FROM specs WHERE domain = ? AND spec_json = ? LIMIT 1",
            (normalized_domain, spec_json),
        ).fetchone()

        if existing:
            success_count = existing["success_count"] + int(success)
            failure_count = existing["failure_count"] + int(not success)
            score = success_count - failure_count
            conn.execute(
                """
                UPDATE specs
                SET success_count = ?, failure_count = ?, score = ?,
                    last_success_at = CASE WHEN ? = 1 THEN ? ELSE last_success_at END,
                    last_failure_at = CASE WHEN ? = 0 THEN ? ELSE last_failure_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    success_count,
                    failure_count,
                    score,
                    int(success),
                    now,
                    int(success),
                    now,
                    now,
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO specs(
                    domain, spec_json, status, score, success_count, failure_count,
                    last_success_at, last_failure_at, created_at, updated_at
                )
                VALUES (?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_domain,
                    spec_json,
                    1 if success else -1,
                    int(success),
                    int(not success),
                    now if success else None,
                    None if success else now,
                    now,
                    now,
                ),
            )


def promote_spec(domain: str, spec: dict[str, Any], db_path: str | Path | None = None) -> bool:
    """Promote a candidate spec to active for a domain."""
    ensure_db_initialized(db_path)
    normalized_domain = domain.lower()
    spec_json = json.dumps(spec, sort_keys=True)
    now = _utc_now()

    if _use_postgres(db_path):
        with _connect_pg() as conn:
            row = conn.execute(
                "SELECT id FROM specs WHERE domain = %s AND spec_json = %s LIMIT 1",
                (normalized_domain, spec_json),
            ).fetchone()
            if not row:
                return False
            conn.execute("UPDATE specs SET status = 'candidate', updated_at = %s WHERE domain = %s", (now, normalized_domain))
            conn.execute(
                "UPDATE specs SET status = 'promoted', promoted_at = %s, updated_at = %s WHERE id = %s",
                (now, now, row["id"]),
            )
            return True

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM specs WHERE domain = ? AND spec_json = ? LIMIT 1",
            (normalized_domain, spec_json),
        ).fetchone()
        if not row:
            return False

        conn.execute("UPDATE specs SET status = 'candidate', updated_at = ? WHERE domain = ?", (now, normalized_domain))
        conn.execute(
            "UPDATE specs SET status = 'promoted', promoted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        return True


def list_specs(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return the best spec per domain (promoted first, then highest score)."""
    ensure_db_initialized(db_path)
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT ON (domain)
                    domain, status, score, success_count, failure_count,
                    last_success_at, created_at, updated_at, spec_json
                FROM specs
                ORDER BY domain,
                    CASE WHEN status = 'promoted' THEN 0 ELSE 1 END,
                    score DESC, updated_at DESC
                """
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            spec = json.loads(d.pop("spec_json", "{}"))
            d["ats"] = spec.get("ats")
            d["data_delivery_type"] = spec.get("data_delivery_type")
            d["api_target_url"] = spec.get("api_target_url")
            result.append(d)
        return result

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT domain, status, score, success_count, failure_count,
                   last_success_at, created_at, updated_at, spec_json
            FROM specs
            ORDER BY domain,
                CASE status WHEN 'promoted' THEN 0 ELSE 1 END,
                score DESC, updated_at DESC
            """
        ).fetchall()

    seen: set[str] = set()
    result = []
    for row in rows:
        d = dict(row)
        if d["domain"] not in seen:
            seen.add(d["domain"])
            spec = json.loads(d.pop("spec_json", "{}"))
            d["ats"] = spec.get("ats")
            d["data_delivery_type"] = spec.get("data_delivery_type")
            d["api_target_url"] = spec.get("api_target_url")
            result.append(d)
    return result


def delete_specs_for_domain(domain: str, db_path: str | Path | None = None) -> int:
    """Delete all specs for a domain so the pipeline re-learns it. Returns rows deleted."""
    ensure_db_initialized(db_path)
    normalized = domain.lower()
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            result = conn.execute("DELETE FROM specs WHERE domain = %s", (normalized,))
            return result.rowcount

    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM specs WHERE domain = ?", (normalized,))
    return cur.rowcount


def save_pipeline_run(result: dict[str, Any], duration_ms: int | None = None, db_path: str | Path | None = None) -> int:
    """Persist a pipeline response and its normalized jobs."""
    ensure_db_initialized(db_path)
    now = _utc_now()
    validation = result.get("validation") or {}
    classification = result.get("classification") or {}
    jobs = result.get("jobs") or []
    response_json = json.dumps(result, sort_keys=True)
    params = (
        result.get("request_id") or "",
        result.get("url") or result.get("requested_url") or result.get("source_url") or "",
        (result.get("domain") or "").lower(),
        int(bool(validation.get("success"))),
        int(validation.get("job_count") if validation.get("job_count") is not None else len(jobs)),
        classification.get("strategy"),
        classification.get("ats"),
        validation.get("notes"),
        duration_ms,
        response_json,
        now,
    )

    if _use_postgres(db_path):
        with _connect_pg() as conn:
            row = conn.execute(
                """
                INSERT INTO pipeline_runs(
                    request_id, url, domain, success, job_count, strategy, ats,
                    notes, duration_ms, response_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                params,
            ).fetchone()
            run_id = int(row["id"])
            _insert_saved_jobs_pg(conn, run_id, jobs, now)
            return run_id

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pipeline_runs(
                request_id, url, domain, success, job_count, strategy, ats,
                notes, duration_ms, response_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        run_id = int(cur.lastrowid)
        _insert_saved_jobs_sqlite(conn, run_id, jobs, now)
        return run_id


def _job_params(run_id: int, job: dict[str, Any], now: str) -> tuple[Any, ...]:
    return (
        run_id,
        job.get("title"),
        json.dumps(job.get("location"), sort_keys=True) if job.get("location") is not None else None,
        job.get("employment_type"),
        job.get("workplace_type"),
        json.dumps(job.get("compensation"), sort_keys=True) if job.get("compensation") is not None else None,
        job.get("job_url"),
        job.get("apply_url"),
        json.dumps(job, sort_keys=True),
        now,
    )


def _insert_saved_jobs_sqlite(conn: sqlite3.Connection, run_id: int, jobs: list[dict[str, Any]], now: str) -> None:
    conn.executemany(
        """
        INSERT INTO saved_jobs(
            run_id, title, location_json, employment_type, workplace_type,
            compensation_json, job_url, apply_url, raw_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_job_params(run_id, job, now) for job in jobs],
    )


def _insert_saved_jobs_pg(conn, run_id: int, jobs: list[dict[str, Any]], now: str) -> None:
    for job in jobs:
        conn.execute(
            """
            INSERT INTO saved_jobs(
                run_id, title, location_json, employment_type, workplace_type,
                compensation_json, job_url, apply_url, raw_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            _job_params(run_id, job, now),
        )


def list_pipeline_runs(limit: int = 50, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return recent saved pipeline runs."""
    ensure_db_initialized(db_path)
    capped_limit = max(1, min(limit, 200))
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            rows = conn.execute(
                """
                SELECT id, request_id, url, domain, success, job_count, strategy,
                       ats, notes, duration_ms, created_at
                FROM pipeline_runs
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (capped_limit,),
            ).fetchall()
        return [_run_row_to_dict(row) for row in rows]

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, request_id, url, domain, success, job_count, strategy,
                   ats, notes, duration_ms, created_at
            FROM pipeline_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (capped_limit,),
        ).fetchall()
    return [_run_row_to_dict(row) for row in rows]


def get_pipeline_run(run_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Return a saved run with its saved jobs and full response."""
    ensure_db_initialized(db_path)
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            row = conn.execute("SELECT * FROM pipeline_runs WHERE id = %s", (run_id,)).fetchone()
            if not row:
                return None
            jobs = conn.execute("SELECT * FROM saved_jobs WHERE run_id = %s ORDER BY id", (run_id,)).fetchall()
        return _run_detail(row, jobs)

    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        jobs = conn.execute("SELECT * FROM saved_jobs WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    return _run_detail(row, jobs)


def clear_pipeline_runs(db_path: str | Path | None = None) -> dict[str, int]:
    """Delete saved runs and jobs while leaving learned specs intact."""
    ensure_db_initialized(db_path)
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            deleted_jobs = conn.execute("DELETE FROM saved_jobs").rowcount
            deleted_runs = conn.execute("DELETE FROM pipeline_runs").rowcount
        return {"runs": deleted_runs, "jobs": deleted_jobs}

    with _connect(db_path) as conn:
        deleted_jobs = conn.execute("DELETE FROM saved_jobs").rowcount
        deleted_runs = conn.execute("DELETE FROM pipeline_runs").rowcount
    return {"runs": deleted_runs, "jobs": deleted_jobs}


def clear_all_data(db_path: str | Path | None = None) -> dict[str, int]:
    """Delete all persisted specs, observations, runs, and jobs."""
    ensure_db_initialized(db_path)
    from scraper.discovery_store import clear_discovery_data
    discovery_deleted = clear_discovery_data(db_path)
    if _use_postgres(db_path):
        with _connect_pg() as conn:
            deleted_jobs = conn.execute("DELETE FROM saved_jobs").rowcount
            deleted_runs = conn.execute("DELETE FROM pipeline_runs").rowcount
            deleted_observations = conn.execute("DELETE FROM observations").rowcount
            deleted_specs = conn.execute("DELETE FROM specs").rowcount
        return {
            "jobs": deleted_jobs,
            "runs": deleted_runs,
            "observations": deleted_observations,
            "specs": deleted_specs,
            **discovery_deleted,
        }

    with _connect(db_path) as conn:
        deleted_jobs = conn.execute("DELETE FROM saved_jobs").rowcount
        deleted_runs = conn.execute("DELETE FROM pipeline_runs").rowcount
        deleted_observations = conn.execute("DELETE FROM observations").rowcount
        deleted_specs = conn.execute("DELETE FROM specs").rowcount
    return {
        "jobs": deleted_jobs,
        "runs": deleted_runs,
        "observations": deleted_observations,
        "specs": deleted_specs,
        **discovery_deleted,
    }


def _run_row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["success"] = bool(d["success"])
    return d


def _run_detail(row, jobs) -> dict[str, Any]:
    run = _run_row_to_dict(row)
    response_json = run.pop("response_json", "{}")
    run["response"] = json.loads(response_json)
    run["jobs"] = [_saved_job_row_to_dict(job) for job in jobs]
    return run


def _saved_job_row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    raw = json.loads(d.pop("raw_json", "{}"))
    d["location"] = json.loads(d.pop("location_json")) if d.get("location_json") else None
    d["compensation"] = json.loads(d.pop("compensation_json")) if d.get("compensation_json") else None
    d["raw"] = raw
    return d


def demote_spec(domain: str, spec: dict[str, Any], db_path: str | Path | None = None) -> bool:
    """Demote a promoted spec back to candidate."""
    ensure_db_initialized(db_path)
    normalized_domain = domain.lower()
    spec_json = json.dumps(spec, sort_keys=True)
    now = _utc_now()

    if _use_postgres(db_path):
        with _connect_pg() as conn:
            result = conn.execute(
                """
                UPDATE specs
                SET status = 'candidate', updated_at = %s
                WHERE domain = %s AND spec_json = %s AND status = 'promoted'
                """,
                (now, normalized_domain, spec_json),
            )
            return result.rowcount > 0

    with _connect(db_path) as conn:
        result = conn.execute(
            """
            UPDATE specs
            SET status = 'candidate', updated_at = ?
            WHERE domain = ? AND spec_json = ? AND status = 'promoted'
            """,
            (now, normalized_domain, spec_json),
        )
    return result.rowcount > 0
