"""Re-apply the IT filter to already-crawled data — no network requests.

Why this exists: filter rules will keep changing as we measure precision. The
raw zone is the source of truth, so classification can be recomputed without
touching TopDev again. This is the payoff of storing raw payloads.

Usage:
    python -m ingestion.reclassify --date 2026-11-26
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from .filter import classify
from .storage import ObjectStore, rejects_key

PAGE_RE = re.compile(r"page=(\d+)\.jsonl$")


def reclassify_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into (kept IT jobs, newly rejected) using the current rules."""
    keep: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    for row in rows:
        job = row.get("job", {})
        is_it, reason = classify(job.get("title"), job.get("skills"))
        if is_it:
            row["filter_reason"] = reason
            keep.append(row)
        else:
            moved.append(
                {
                    "source_id": row.get("source_id"),
                    "title": job.get("title"),
                    "reason": reason,
                }
            )
    return keep, moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)

    store = ObjectStore.from_settings()
    dt = args.date
    keys = store.list_keys(f"jobs/dt={dt}/")
    if not keys:
        print(f"no jobs partitions for dt={dt}")
        return 1

    before = after = removed = 0
    for key in keys:
        match = PAGE_RE.search(key)
        page = int(match.group(1)) if match else 0
        text = store.get_text(key) or ""
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        keep, moved = reclassify_rows(rows)

        before += len(rows)
        after += len(keep)
        removed += len(moved)

        store.put_jsonl(key, keep)
        if moved:
            existing_text = store.get_text(rejects_key(dt, page)) or ""
            existing = [json.loads(line) for line in existing_text.splitlines() if line.strip()]
            store.put_jsonl(rejects_key(dt, page), existing + moved)
        print(f"page {page:03d}: {len(rows):2} -> {len(keep):2} kept, {len(moved):2} moved to rejects")

    print(f"\ndone: {before} rows -> {after} kept ({removed} reclassified as non-IT)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
