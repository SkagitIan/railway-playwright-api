"""Simple SQLite-backed store for learned scraping specs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/spec_store.sqlite3")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path | None = None) -> None:
    """Create minimal tables if they do not exist."""
    with _connect(db_path) as conn:
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


def get_promoted_spec(domain: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Return latest promoted spec for a domain."""
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
    normalized_domain = domain.lower()
    spec_json = json.dumps(spec, sort_keys=True)
    now = _utc_now()

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
    normalized_domain = domain.lower()
    spec_json = json.dumps(spec, sort_keys=True)
    now = _utc_now()

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
    normalized_domain = domain.lower()
    spec_json = json.dumps(spec, sort_keys=True)
    now = _utc_now()

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
