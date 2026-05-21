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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_specs_domain_status ON specs(domain, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_domain ON observations(domain)")
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_specs_domain_status ON specs(domain, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_domain ON observations(domain)")
    _INITIALIZED_DB_PATHS.add(path.resolve())


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
