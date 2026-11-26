"""Day 4 — load the raw JSONL files from MinIO into Postgres.

Why an upsert and not an insert: the crawler may see the same posting on several
days (it stays online). The warehouse keeps **one row per posting**, updated
with the newest payload, while ``first_seen_at`` preserves when we found it.

Why ``RETURNING (xmax = 0)``: in Postgres, ``xmax = 0`` is true only for rows
this statement *inserted* (updated rows carry the previous transaction id), so
one statement gives us both the insert/update counts used in the run summary.

Usage:
    python -m ingestion.load                 # today's partition
    python -m ingestion.load --date 2026-11-26
    python -m ingestion.load --all           # every partition in the bucket
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .config import Settings, get_settings
from .storage import ObjectStore

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.job_postings (
    source_id     text PRIMARY KEY,
    source        text        NOT NULL,
    dt            date        NOT NULL,
    company_id    text,
    title         text,
    company       text,
    is_it_job     boolean     NOT NULL DEFAULT true,
    filter_reason text,
    payload       jsonb       NOT NULL,
    crawled_at    timestamptz,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_job_postings_dt ON raw.job_postings (dt);
CREATE INDEX IF NOT EXISTS idx_raw_job_postings_source ON raw.job_postings (source);
"""

UPSERT_SQL = """
INSERT INTO raw.job_postings (
    source_id, source, dt, company_id, title, company,
    is_it_job, filter_reason, payload, crawled_at
)
VALUES (
    %(source_id)s, %(source)s, %(dt)s, %(company_id)s, %(title)s, %(company)s,
    %(is_it_job)s, %(filter_reason)s, %(payload)s, %(crawled_at)s
)
ON CONFLICT (source_id) DO UPDATE SET
    dt            = EXCLUDED.dt,
    company_id    = EXCLUDED.company_id,
    title         = EXCLUDED.title,
    company       = EXCLUDED.company,
    is_it_job     = EXCLUDED.is_it_job,
    filter_reason = EXCLUDED.filter_reason,
    payload       = EXCLUDED.payload,
    crawled_at    = EXCLUDED.crawled_at,
    last_seen_at  = now()
RETURNING (xmax = 0) AS inserted
"""

DT_IN_KEY_RE = re.compile(r"dt=(\d{4}-\d{2}-\d{2})")


# --------------------------------------------------------------------------- #
# pure helpers (unit tested without a database)
# --------------------------------------------------------------------------- #
def parse_jsonl(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def record_params(row: dict[str, Any]) -> dict[str, Any]:
    """Map one raw JSONL record onto the SQL parameters."""
    job = row.get("job") or {}
    crawled_at = row.get("crawled_at")
    return {
        "source_id": row["source_id"],
        "source": row.get("source", "topdev"),
        "dt": row["dt"],
        "company_id": job.get("company_id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "is_it_job": bool(row.get("is_it_job", True)),
        "filter_reason": row.get("filter_reason"),
        "payload": Jsonb(job),
        "crawled_at": datetime.fromisoformat(crawled_at) if crawled_at else None,
    }


def dates_in_bucket(keys: list[str]) -> list[str]:
    return sorted({m.group(1) for key in keys if (m := DT_IN_KEY_RE.search(key))})


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def upsert_rows(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> tuple[int, int]:
    inserted = updated = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(UPSERT_SQL, record_params(row))
            if cur.fetchone()[0]:
                inserted += 1
            else:
                updated += 1
    conn.commit()
    return inserted, updated


def load_date(
    store: ObjectStore, conn: psycopg.Connection, dt: str
) -> dict[str, int]:
    keys = store.list_keys(f"jobs/dt={dt}/")
    rows: list[dict[str, Any]] = []
    for key in keys:
        rows.extend(parse_jsonl(store.get_text(key) or ""))

    inserted, updated = upsert_rows(conn, rows)
    return {
        "dt": dt,
        "files": len(keys),
        "rows": len(rows),
        "inserted": inserted,
        "updated": updated,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="partition to load (default: today)")
    parser.add_argument("--all", action="store_true", help="load every partition")
    args = parser.parse_args(argv)

    settings: Settings = get_settings()
    store = ObjectStore.from_settings(settings)

    if args.all:
        dates = dates_in_bucket(store.list_keys("jobs/"))
    elif args.date:
        dates = [args.date]
    else:
        dates = [datetime.now().date().isoformat()]

    if not dates:
        print("no partitions found under jobs/")
        return 1

    with psycopg.connect(settings.dsn) as conn:
        ensure_schema(conn)
        totals = {"rows": 0, "inserted": 0, "updated": 0}
        for dt in dates:
            stats = load_date(store, conn, dt)
            if stats["rows"] == 0:
                print(f"{dt}: no rows (partition empty or missing)")
                continue
            print(
                f"{dt}: {stats['files']} file(s) -> {stats['rows']} rows "
                f"| inserted={stats['inserted']} updated={stats['updated']}"
            )
            for key in totals:
                totals[key] += stats[key]

    print(
        f"\nloaded {len(dates)} partition(s) | rows={totals['rows']} "
        f"inserted={totals['inserted']} updated={totals['updated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
