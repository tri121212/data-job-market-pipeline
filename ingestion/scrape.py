"""Day 3 — the crawler: sitemap -> filter -> MinIO raw zone, resumable.

Design notes (the "why" matters more than the code):

* **Idempotent by partition**: everything is written under ``dt=YYYY-MM-DD``,
  so re-running on the same day overwrites today's files instead of appending
  duplicates. Yesterday's data is never touched.
* **Resume at page granularity**: ``_state/dt=.../pages_done.json`` records
  finished pages. A crashed run picks up where it stopped instead of re-fetching
  hundreds of pages.
* **Fail soft**: one broken job page must not kill the whole run. Errors are
  counted and reported; the page is retried on the next run.
* **Audit the filter**: rejected *titles* are stored under ``_rejects/`` so the
  keyword rules can be tuned with evidence instead of guesses.

Usage:
    python -m ingestion.scrape --pages 20
    python -m ingestion.scrape --date 2026-11-26 --pages 2 --verbose
    python -m ingestion.scrape --pages 20 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from tenacity import RetryError

from .config import Settings, get_settings
from .explore import fetch, job_id_from_url, parse_jobposting, sitemap_job_urls
from .filter import classify
from .storage import (
    ObjectStore,
    html_key,
    jobs_key,
    meta_key,
    rejects_key,
    state_key,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def load_state(store: ObjectStore, dt: str) -> dict[str, Any]:
    state = store.get_json(state_key(dt)) or {}
    return {
        "dt": dt,
        "done_pages": list(state.get("done_pages", [])),
        "failed_pages": list(state.get("failed_pages", [])),
        "updated_at": state.get("updated_at"),
    }


def save_state(store: ObjectStore, dt: str, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
    store.put_json(state_key(dt), state)


# --------------------------------------------------------------------------- #
# crawl
# --------------------------------------------------------------------------- #
@dataclass
class PageResult:
    page: int
    ok: bool = False
    warnings: list[str] = field(default_factory=list)
    jobs_seen: int = 0
    jobs_skipped: int = 0
    jobs_it: int = 0
    jobs_rejected: int = 0
    jobs_duplicate: int = 0


def crawl_page(
    page: int,
    dt: str,
    store: ObjectStore,
    session: requests.Session,
    settings: Settings,
    seen_ids: set[str],
    verbose: bool = False,
) -> PageResult:
    """Crawl one sitemap page and persist its IT jobs + reject audit trail."""
    result = PageResult(page=page)
    try:
        urls = sitemap_job_urls(page, session)
    except (requests.RequestException, RetryError) as exc:
        result.warnings.append(f"sitemap page {page} failed: {exc}")
        return result

    if not urls:
        result.warnings.append(f"sitemap page {page} returned no job URLs")
        return result

    it_records: list[dict[str, Any]] = []
    rejects: list[dict[str, str]] = []
    crawled_at = datetime.now(VN_TZ).isoformat(timespec="seconds")

    for url in urls:
        result.jobs_seen += 1

        # Cheap pre-filter: the slug carries the title. If it clearly is a
        # non-IT role (sales, accounting...), skip the network request entirely.
        slug = url.rsplit("/", 1)[-1]
        slug_title = re.sub(r"-\d+$", "", slug).replace("-", " ")
        _, slug_reason = classify(slug_title, [])
        if slug_reason.startswith("non_it:"):
            result.jobs_skipped += 1
            result.jobs_rejected += 1
            rejects.append(
                {
                    "source_id": job_id_from_url(url) or slug,
                    "title": slug_title,
                    "reason": f"{slug_reason}:slug",
                }
            )
            continue

        try:
            html = fetch(url, session)
            time.sleep(settings.request_delay_seconds)
        except (requests.RequestException, RetryError) as exc:
            result.warnings.append(f"{url}: {exc}")
            continue

        job = parse_jobposting(html, url)
        if job is None:
            result.warnings.append(f"{url}: no JobPosting JSON-LD")
            continue

        if job["source_id"] in seen_ids:
            result.jobs_duplicate += 1
            continue
        seen_ids.add(job["source_id"])

        is_it, reason = classify(job["title"], job["skills"])
        if not is_it:
            result.jobs_rejected += 1
            rejects.append({"source_id": job["source_id"], "title": job["title"], "reason": reason})
            continue

        result.jobs_it += 1
        job["is_it_job"] = True
        job["filter_reason"] = reason
        it_records.append(
            {
                "source": job["source"],
                "source_id": job["source_id"],
                "dt": dt,
                "sitemap_page": page,
                "crawled_at": crawled_at,
                "is_it_job": True,
                "filter_reason": reason,
                "job": job,
            }
        )
        store.put_html(html_key(dt, job["source_id"]), html)

        if verbose:
            print(f"    + {job['title'][:60]}")

    store.put_jsonl(jobs_key(dt, page), it_records)
    if rejects:
        store.put_jsonl(rejects_key(dt, page), rejects)

    result.ok = True
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl TopDev IT jobs into the raw zone")
    parser.add_argument("--date", default=datetime.now(VN_TZ).strftime("%Y-%m-%d"))
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--delay", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.pages is not None:
        settings = settings.model_copy(update={"max_pages_per_run": args.pages})
    if args.delay is not None:
        settings = settings.model_copy(update={"request_delay_seconds": args.delay})

    dt = args.date
    total_pages = settings.max_pages_per_run
    store = ObjectStore.from_settings(settings)
    state = load_state(store, dt)
    done = set(state["done_pages"])
    pages = [p for p in range(1, total_pages + 1) if p not in done]

    print(f"date={dt}  pages={total_pages}  already_done={sorted(done)}  to_crawl={len(pages)}")
    if args.dry_run:
        for page in pages:
            print(f"  would crawl page {page} -> {jobs_key(dt, page)}")
        print("dry-run: nothing fetched, nothing written")
        return 0
    if not pages:
        print("nothing to do: all pages finished for this date")
        return 0

    started = time.monotonic()
    seen_ids: set[str] = set()
    summary = {
        "dt": dt,
        "pages_ok": 0,
        "pages_failed": 0,
        "jobs_seen": 0,
        "jobs_skipped": 0,
        "jobs_it": 0,
        "jobs_rejected": 0,
        "jobs_duplicate": 0,
    }

    with requests.Session() as session:
        for page in pages:
            result = crawl_page(page, dt, store, session, settings, seen_ids, args.verbose)

            if result.ok:
                state["done_pages"] = sorted({*state["done_pages"], page})
                state["failed_pages"] = [p for p in state["failed_pages"] if p != page]
                summary["pages_ok"] += 1
            else:
                state["failed_pages"] = sorted({*state["failed_pages"], page})
                summary["pages_failed"] += 1
            save_state(store, dt, state)  # persist after every page -> crash-safe

            summary["jobs_seen"] += result.jobs_seen
            summary["jobs_skipped"] += result.jobs_skipped
            summary["jobs_it"] += result.jobs_it
            summary["jobs_rejected"] += result.jobs_rejected
            summary["jobs_duplicate"] += result.jobs_duplicate

            status = "ok" if result.ok else "FAILED"
            print(
                f"page {page:03d} {status:6} | seen={result.jobs_seen:2} "
                f"skip={result.jobs_skipped:2} "
                f"it={result.jobs_it:2} rejected={result.jobs_rejected:2} "
                f"dup={result.jobs_duplicate:2}"
            )
            for warning in result.warnings:
                print(f"    ! {warning}", file=sys.stderr)

    summary["elapsed_seconds"] = round(time.monotonic() - started, 1)
    summary["finished_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
    store.put_json(meta_key(dt), summary)

    print(
        f"\ndone in {summary['elapsed_seconds']}s | pages_ok={summary['pages_ok']} "
        f"pages_failed={summary['pages_failed']} | jobs_seen={summary['jobs_seen']} "
        f"skipped={summary['jobs_skipped']} "
        f"jobs_it={summary['jobs_it']} rejected={summary['jobs_rejected']} "
        f"duplicate={summary['jobs_duplicate']}"
    )
    return 0 if summary["pages_failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
