"""Persistence helpers for Google Places business discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scraper.ats import spec_store


DISCOVERY_SKU = "places_text_search_enterprise"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _loads(value: str | None, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _month_key(now: str | None = None) -> str:
    return (now or spec_store._utc_now())[:7]


def init_discovery_tables(db_path: str | Path | None = None) -> None:
    """Create discovery tables for SQLite or Postgres."""
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    id BIGSERIAL PRIMARY KEY,
                    query TEXT NOT NULL,
                    industry TEXT,
                    cities_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    google_calls INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_businesses (
                    id BIGSERIAL PRIMARY KEY,
                    place_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    formatted_address TEXT,
                    short_formatted_address TEXT,
                    website_uri TEXT,
                    google_maps_uri TEXT,
                    primary_type TEXT,
                    business_status TEXT,
                    raw_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_items (
                    id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
                    business_id BIGINT NOT NULL REFERENCES discovery_businesses(id) ON DELETE CASCADE,
                    query TEXT NOT NULL,
                    city TEXT NOT NULL,
                    source_status TEXT NOT NULL DEFAULT 'pending',
                    source_url TEXT,
                    source_type TEXT,
                    source_confidence DOUBLE PRECISION,
                    source_reason TEXT,
                    source_citations_json TEXT,
                    jobs_status TEXT NOT NULL DEFAULT 'not_run',
                    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(run_id, business_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_usage (
                    provider TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    month TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(provider, sku, month)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discovery_items_run_id ON discovery_items(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discovery_usage_month ON discovery_usage(month)")
        return

    with spec_store._connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                industry TEXT,
                cities_json TEXT NOT NULL,
                status TEXT NOT NULL,
                google_calls INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                place_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                formatted_address TEXT,
                short_formatted_address TEXT,
                website_uri TEXT,
                google_maps_uri TEXT,
                primary_type TEXT,
                business_status TEXT,
                raw_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                business_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                city TEXT NOT NULL,
                source_status TEXT NOT NULL DEFAULT 'pending',
                source_url TEXT,
                source_type TEXT,
                source_confidence REAL,
                source_reason TEXT,
                source_citations_json TEXT,
                jobs_status TEXT NOT NULL DEFAULT 'not_run',
                pipeline_run_id INTEGER,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, business_id),
                FOREIGN KEY(run_id) REFERENCES discovery_runs(id) ON DELETE CASCADE,
                FOREIGN KEY(business_id) REFERENCES discovery_businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(pipeline_run_id) REFERENCES pipeline_runs(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_usage (
                provider TEXT NOT NULL,
                sku TEXT NOT NULL,
                month TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(provider, sku, month)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_discovery_items_run_id ON discovery_items(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_discovery_usage_month ON discovery_usage(month)")


def create_discovery_run(query: str, industry: str | None, cities: list[str], db_path: str | Path | None = None) -> int:
    spec_store.ensure_db_initialized(db_path)
    now = spec_store._utc_now()
    params = (query, industry, _json(cities), "running", 0, None, now, now)
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            row = conn.execute(
                """
                INSERT INTO discovery_runs(query, industry, cities_json, status, google_calls, error, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                params,
            ).fetchone()
            return int(row["id"])
    with spec_store._connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO discovery_runs(query, industry, cities_json, status, google_calls, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        return int(cur.lastrowid)


def update_discovery_run(run_id: int, *, status: str, google_calls: int | None = None, error: str | None = None, db_path: str | Path | None = None) -> None:
    spec_store.ensure_db_initialized(db_path)
    now = spec_store._utc_now()
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            conn.execute(
                """
                UPDATE discovery_runs
                SET status = %s,
                    google_calls = COALESCE(%s, google_calls),
                    error = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (status, google_calls, error, now, run_id),
            )
        return
    with spec_store._connect(db_path) as conn:
        conn.execute(
            """
            UPDATE discovery_runs
            SET status = ?,
                google_calls = COALESCE(?, google_calls),
                error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, google_calls, error, now, run_id),
        )


def reserve_google_usage(count: int, limit: int, db_path: str | Path | None = None) -> dict[str, int | str]:
    """Atomically reserve Google usage or raise ValueError if it exceeds the cap."""
    spec_store.ensure_db_initialized(db_path)
    month = _month_key()
    now = spec_store._utc_now()
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            row = conn.execute(
                "SELECT used FROM discovery_usage WHERE provider = %s AND sku = %s AND month = %s FOR UPDATE",
                ("google", DISCOVERY_SKU, month),
            ).fetchone()
            used = int(row["used"]) if row else 0
            if used + count > limit:
                raise ValueError(f"Google Places monthly limit would be exceeded: {used + count}/{limit}")
            if row:
                conn.execute(
                    "UPDATE discovery_usage SET used = %s, updated_at = %s WHERE provider = %s AND sku = %s AND month = %s",
                    (used + count, now, "google", DISCOVERY_SKU, month),
                )
            else:
                conn.execute(
                    "INSERT INTO discovery_usage(provider, sku, month, used, updated_at) VALUES (%s, %s, %s, %s, %s)",
                    ("google", DISCOVERY_SKU, month, count, now),
                )
            return {"used": used + count, "remaining": limit - used - count, "limit": limit, "month": month}

    with spec_store._connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT used FROM discovery_usage WHERE provider = ? AND sku = ? AND month = ?",
            ("google", DISCOVERY_SKU, month),
        ).fetchone()
        used = int(row["used"]) if row else 0
        if used + count > limit:
            raise ValueError(f"Google Places monthly limit would be exceeded: {used + count}/{limit}")
        if row:
            conn.execute(
                "UPDATE discovery_usage SET used = ?, updated_at = ? WHERE provider = ? AND sku = ? AND month = ?",
                (used + count, now, "google", DISCOVERY_SKU, month),
            )
        else:
            conn.execute(
                "INSERT INTO discovery_usage(provider, sku, month, used, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("google", DISCOVERY_SKU, month, count, now),
            )
        return {"used": used + count, "remaining": limit - used - count, "limit": limit, "month": month}


def get_google_usage(limit: int, db_path: str | Path | None = None) -> dict[str, int | str]:
    spec_store.ensure_db_initialized(db_path)
    month = _month_key()
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            row = conn.execute(
                "SELECT used FROM discovery_usage WHERE provider = %s AND sku = %s AND month = %s",
                ("google", DISCOVERY_SKU, month),
            ).fetchone()
        used = int(row["used"]) if row else 0
        return {"used": used, "remaining": max(0, limit - used), "limit": limit, "month": month}
    with spec_store._connect(db_path) as conn:
        row = conn.execute(
            "SELECT used FROM discovery_usage WHERE provider = ? AND sku = ? AND month = ?",
            ("google", DISCOVERY_SKU, month),
        ).fetchone()
    used = int(row["used"]) if row else 0
    return {"used": used, "remaining": max(0, limit - used), "limit": limit, "month": month}


def upsert_discovery_item(run_id: int, query: str, city: str, place: dict[str, Any], db_path: str | Path | None = None) -> int:
    spec_store.ensure_db_initialized(db_path)
    now = spec_store._utc_now()
    place_id = place["id"]
    display_name = place.get("displayName") or {}
    name = display_name.get("text") or place.get("name") or place_id
    params = (
        place_id,
        name,
        place.get("formattedAddress"),
        place.get("shortFormattedAddress"),
        place.get("websiteUri"),
        place.get("googleMapsUri"),
        place.get("primaryType"),
        place.get("businessStatus"),
        _json(place),
        now,
        now,
    )
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            row = conn.execute(
                """
                INSERT INTO discovery_businesses(
                    place_id, name, formatted_address, short_formatted_address, website_uri,
                    google_maps_uri, primary_type, business_status, raw_json, first_seen_at, last_seen_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (place_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    formatted_address = EXCLUDED.formatted_address,
                    short_formatted_address = EXCLUDED.short_formatted_address,
                    website_uri = EXCLUDED.website_uri,
                    google_maps_uri = EXCLUDED.google_maps_uri,
                    primary_type = EXCLUDED.primary_type,
                    business_status = EXCLUDED.business_status,
                    raw_json = EXCLUDED.raw_json,
                    last_seen_at = EXCLUDED.last_seen_at
                RETURNING id
                """,
                params,
            ).fetchone()
            business_id = int(row["id"])
            item = conn.execute(
                """
                INSERT INTO discovery_items(run_id, business_id, query, city, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, business_id) DO UPDATE SET updated_at = EXCLUDED.updated_at
                RETURNING id
                """,
                (run_id, business_id, query, city, now, now),
            ).fetchone()
            return int(item["id"])

    with spec_store._connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO discovery_businesses(
                place_id, name, formatted_address, short_formatted_address, website_uri,
                google_maps_uri, primary_type, business_status, raw_json, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                name = excluded.name,
                formatted_address = excluded.formatted_address,
                short_formatted_address = excluded.short_formatted_address,
                website_uri = excluded.website_uri,
                google_maps_uri = excluded.google_maps_uri,
                primary_type = excluded.primary_type,
                business_status = excluded.business_status,
                raw_json = excluded.raw_json,
                last_seen_at = excluded.last_seen_at
            """,
            params,
        )
        row = conn.execute("SELECT id FROM discovery_businesses WHERE place_id = ?", (place_id,)).fetchone()
        business_id = int(row["id"])
        conn.execute(
            """
            INSERT INTO discovery_items(run_id, business_id, query, city, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, business_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (run_id, business_id, query, city, now, now),
        )
        item = conn.execute("SELECT id FROM discovery_items WHERE run_id = ? AND business_id = ?", (run_id, business_id)).fetchone()
        return int(item["id"])


def list_discovery_runs(limit: int = 50, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    spec_store.ensure_db_initialized(db_path)
    capped = max(1, min(limit, 200))
    sql = """
        SELECT r.*, COUNT(i.id) AS item_count
        FROM discovery_runs r
        LEFT JOIN discovery_items i ON i.run_id = r.id
        GROUP BY r.id
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT {limit}
    """
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            rows = conn.execute(sql.format(limit="%s"), (capped,)).fetchall()
        return [_run_dict(row) for row in rows]
    with spec_store._connect(db_path) as conn:
        rows = conn.execute(sql.format(limit="?"), (capped,)).fetchall()
    return [_run_dict(row) for row in rows]


def get_discovery_run(run_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    spec_store.ensure_db_initialized(db_path)
    run_sql = "SELECT * FROM discovery_runs WHERE id = %s" if spec_store._use_postgres(db_path) else "SELECT * FROM discovery_runs WHERE id = ?"
    item_sql = """
        SELECT i.*, b.place_id, b.name, b.formatted_address, b.short_formatted_address,
               b.website_uri, b.google_maps_uri, b.primary_type, b.business_status, b.raw_json
        FROM discovery_items i
        JOIN discovery_businesses b ON b.id = i.business_id
        WHERE i.run_id = {placeholder}
        ORDER BY b.name, i.id
    """
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            run = conn.execute(run_sql, (run_id,)).fetchone()
            if not run:
                return None
            rows = conn.execute(item_sql.format(placeholder="%s"), (run_id,)).fetchall()
        result = _run_dict(run)
        result["items"] = [_item_dict(row) for row in rows]
        return result

    with spec_store._connect(db_path) as conn:
        run = conn.execute(run_sql, (run_id,)).fetchone()
        if not run:
            return None
        rows = conn.execute(item_sql.format(placeholder="?"), (run_id,)).fetchall()
    result = _run_dict(run)
    result["items"] = [_item_dict(row) for row in rows]
    return result


def get_discovery_items(run_id: int, item_ids: list[int] | None = None, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    run = get_discovery_run(run_id, db_path=db_path)
    if not run:
        return []
    items = run["items"]
    if item_ids is None:
        return items
    wanted = set(item_ids)
    return [item for item in items if item["id"] in wanted]


def delete_discovery_items(run_id: int, item_ids: list[int], db_path: str | Path | None = None) -> int:
    spec_store.ensure_db_initialized(db_path)
    if not item_ids:
        return 0
    ids = sorted({int(item_id) for item_id in item_ids})
    if spec_store._use_postgres(db_path):
        placeholders = ", ".join(["%s"] * len(ids))
        with spec_store._connect_pg() as conn:
            deleted = conn.execute(
                f"DELETE FROM discovery_items WHERE run_id = %s AND id IN ({placeholders})",
                (run_id, *ids),
            ).rowcount
            conn.execute(
                """
                DELETE FROM discovery_businesses b
                WHERE NOT EXISTS (
                    SELECT 1 FROM discovery_items i WHERE i.business_id = b.id
                )
                """
            )
        return int(deleted or 0)

    placeholders = ", ".join(["?"] * len(ids))
    with spec_store._connect(db_path) as conn:
        deleted = conn.execute(
            f"DELETE FROM discovery_items WHERE run_id = ? AND id IN ({placeholders})",
            (run_id, *ids),
        ).rowcount
        conn.execute(
            """
            DELETE FROM discovery_businesses
            WHERE NOT EXISTS (
                SELECT 1 FROM discovery_items WHERE discovery_items.business_id = discovery_businesses.id
            )
            """
        )
    return int(deleted or 0)


def update_discovery_source(item_id: int, payload: dict[str, Any], db_path: str | Path | None = None) -> None:
    spec_store.ensure_db_initialized(db_path)
    now = spec_store._utc_now()
    source_url = payload.get("source_url")
    status = "found" if source_url else "not_found"
    params = (
        status,
        source_url,
        payload.get("source_type"),
        payload.get("confidence"),
        payload.get("reason"),
        _json(payload.get("citations") or []),
        None,
        now,
        item_id,
    )
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            conn.execute(
                """
                UPDATE discovery_items
                SET source_status = %s, source_url = %s, source_type = %s, source_confidence = %s,
                    source_reason = %s, source_citations_json = %s, error = %s, updated_at = %s
                WHERE id = %s
                """,
                params,
            )
        return
    with spec_store._connect(db_path) as conn:
        conn.execute(
            """
            UPDATE discovery_items
            SET source_status = ?, source_url = ?, source_type = ?, source_confidence = ?,
                source_reason = ?, source_citations_json = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            params,
        )


def update_discovery_error(item_id: int, *, source_status: str | None = None, jobs_status: str | None = None, error: str, db_path: str | Path | None = None) -> None:
    spec_store.ensure_db_initialized(db_path)
    now = spec_store._utc_now()
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            conn.execute(
                """
                UPDATE discovery_items
                SET source_status = COALESCE(%s, source_status),
                    jobs_status = COALESCE(%s, jobs_status),
                    error = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (source_status, jobs_status, error, now, item_id),
            )
        return
    with spec_store._connect(db_path) as conn:
        conn.execute(
            """
            UPDATE discovery_items
            SET source_status = COALESCE(?, source_status),
                jobs_status = COALESCE(?, jobs_status),
                error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (source_status, jobs_status, error, now, item_id),
        )


def update_discovery_jobs(item_id: int, *, status: str, pipeline_run_id: int | None = None, error: str | None = None, db_path: str | Path | None = None) -> None:
    spec_store.ensure_db_initialized(db_path)
    now = spec_store._utc_now()
    params = (status, pipeline_run_id, error, now, item_id)
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            conn.execute(
                "UPDATE discovery_items SET jobs_status = %s, pipeline_run_id = %s, error = %s, updated_at = %s WHERE id = %s",
                params,
            )
        return
    with spec_store._connect(db_path) as conn:
        conn.execute(
            "UPDATE discovery_items SET jobs_status = ?, pipeline_run_id = ?, error = ?, updated_at = ? WHERE id = ?",
            params,
        )


def clear_discovery_data(db_path: str | Path | None = None) -> dict[str, int]:
    spec_store.ensure_db_initialized(db_path)
    if spec_store._use_postgres(db_path):
        with spec_store._connect_pg() as conn:
            items = conn.execute("DELETE FROM discovery_items").rowcount
            businesses = conn.execute("DELETE FROM discovery_businesses").rowcount
            runs = conn.execute("DELETE FROM discovery_runs").rowcount
            usage = conn.execute("DELETE FROM discovery_usage").rowcount
        return {"discovery_items": items, "discovery_businesses": businesses, "discovery_runs": runs, "discovery_usage": usage}
    with spec_store._connect(db_path) as conn:
        items = conn.execute("DELETE FROM discovery_items").rowcount
        businesses = conn.execute("DELETE FROM discovery_businesses").rowcount
        runs = conn.execute("DELETE FROM discovery_runs").rowcount
        usage = conn.execute("DELETE FROM discovery_usage").rowcount
    return {"discovery_items": items, "discovery_businesses": businesses, "discovery_runs": runs, "discovery_usage": usage}


def _run_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["cities"] = _loads(d.pop("cities_json", None), [])
    return d


def _item_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["raw_google_place"] = _loads(d.pop("raw_json", None), {})
    d["source_citations"] = _loads(d.pop("source_citations_json", None), [])
    return d
