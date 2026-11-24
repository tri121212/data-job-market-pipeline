"""Day 2 — explore the TopDev job source.

What this does:
1. Reads a TopDev sitemap page to discover job detail URLs.
2. Fetches a handful of them politely (1 request/second, retries with backoff).
3. Parses the ``JobPosting`` JSON-LD block embedded in each page.
4. Prints a normalized summary and can dump the raw HTML for fixtures.

Why JSON-LD instead of scraping the visual layout: the markup is stable,
schema.org-typed, and carries every field we need (salary, skills, location).

Usage:
    python -m ingestion.explore --sitemap-page 1 --limit 5
    python -m ingestion.explore --limit 3 --save docs/samples/live
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

SITEMAP_PAGE_URL = "https://topdev.vn/sitemap/jobs_desc_en_page_{page}.xml"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 1.0
JSON_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def fetch(url: str, session: requests.Session | None = None, timeout: int = 30) -> str:
    """GET a URL as text, retrying transient failures with exponential backoff."""
    sess = session or requests
    response = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def sitemap_job_urls(page: int = 1, session: requests.Session | None = None) -> list[str]:
    """Return the job detail URLs listed on one TopDev sitemap page (20 per page)."""
    xml = fetch(SITEMAP_PAGE_URL.format(page=page), session)
    return re.findall(r"<loc>(https://topdev\.vn/detail-jobs/[^<]+)</loc>", xml)


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _first(value: Any) -> Any:
    """schema.org allows a single object or a list of them."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _parse_salary(base_salary: Any) -> dict[str, Any]:
    """Normalize schema.org MonetaryAmount, including the "Negotiable" variant."""
    result: dict[str, Any] = {
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "salary_unit": None,
        "is_salary_negotiable": True,
    }
    if not isinstance(base_salary, dict):
        return result

    result["currency"] = base_salary.get("currency")
    amount = base_salary.get("value")

    if isinstance(amount, dict):
        result["salary_unit"] = amount.get("unitText")
        result["salary_min"] = _to_int(amount.get("minValue"))
        result["salary_max"] = _to_int(amount.get("maxValue"))
    elif isinstance(amount, str):
        result["salary_min"] = _to_int(amount)
        result["salary_max"] = result["salary_min"]

    result["is_salary_negotiable"] = (
        result["salary_min"] is None and result["salary_max"] is None
    )
    return result


def _parse_skills(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _parse_location(job_location: Any) -> dict[str, str | None]:
    place = _first(job_location) or {}
    address = place.get("address") or {}
    return {
        "location_city": address.get("addressLocality"),
        "location_region": address.get("addressRegion"),
        "location_country": address.get("addressCountry"),
    }


def _html_to_text(html: str | None) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def parse_jobposting(html: str, url: str | None = None) -> dict[str, Any] | None:
    """Extract a normalized job dict from a TopDev detail page.

    Returns ``None`` when the page carries no JobPosting block.
    """
    payload: dict[str, Any] | None = None
    for raw_block in JSON_LD_RE.findall(html):
        try:
            block = json.loads(raw_block)
        except json.JSONDecodeError:
            continue
        if isinstance(block, dict) and block.get("@type") == "JobPosting":
            payload = block
            break

    if payload is None:
        return None

    identifier = payload.get("identifier") or {}
    source_id = identifier.get("value") if isinstance(identifier, dict) else None
    if source_id is None:
        source_id = hashlib.sha256((url or "").encode()).hexdigest()[:16]

    org = payload.get("hiringOrganization") or {}
    apply_url = (payload.get("potentialAction") or {}).get("target") or url

    job: dict[str, Any] = {
        "source": "topdev",
        "source_id": str(source_id),
        "url": apply_url,
        "title": (payload.get("title") or "").strip(),
        "company": (org.get("name") or "").strip(),
        "company_url": org.get("sameAs"),
        "industry": payload.get("industry"),
        "posted_at": payload.get("datePosted"),
        "valid_through": payload.get("validThrough"),
        "skills": _parse_skills(payload.get("skills")),
        "employment_type": payload.get("employmentType"),
        "description_html": payload.get("description"),
        "description_text": _html_to_text(payload.get("description")),
    }
    job.update(_parse_salary(payload.get("baseSalary")))
    job.update(_parse_location(payload.get("jobLocation")))
    return job


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _format_salary(job: dict[str, Any]) -> str:
    if job["is_salary_negotiable"]:
        return "Thoả thuận"
    low, high = job["salary_min"], job["salary_max"]
    if low and high and low != high:
        return f"{low / 1e6:.0f}-{high / 1e6:.0f}tr"
    return f"{(low or high or 0) / 1e6:.0f}tr"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sitemap-page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--save", type=Path, help="save raw HTML (gzip) to this directory")
    parser.add_argument("--out", type=Path, help="write normalized jobs as JSONL")
    args = parser.parse_args(argv)

    with requests.Session() as session:
        urls = sitemap_job_urls(args.sitemap_page, session)
        if not urls:
            print(f"no job URLs found on sitemap page {args.sitemap_page}", file=sys.stderr)
            return 1
        print(f"sitemap page {args.sitemap_page}: {len(urls)} job URLs discovered\n")

        jobs: list[dict[str, Any]] = []
        for index, url in enumerate(urls[: args.limit], start=1):
            try:
                html = fetch(url, session)
            except requests.RequestException as exc:
                print(f"  [{index}] fetch failed: {exc}", file=sys.stderr)
                continue

            job = parse_jobposting(html, url)
            if job is None:
                print(f"  [{index}] no JobPosting JSON-LD, skipped", file=sys.stderr)
                continue

            jobs.append(job)
            skills = ", ".join(job["skills"][:3]) or "-"
            print(
                f"  [{index}] {job['title'][:44]:<44} | {job['company'][:24]:<24} "
                f"| {_format_salary(job):>12} | {job['location_region'] or '-':<12} | {skills}"
            )

            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                path = args.save / f"topdev_{job['source_id']}.html.gz"
                path.write_bytes(gzip.compress(html.encode("utf-8")))
            time.sleep(REQUEST_DELAY_SECONDS)

    if args.out and jobs:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as handle:
            for job in jobs:
                handle.write(json.dumps(job, ensure_ascii=False) + "\n")

    print(f"\nparsed {len(jobs)} job(s)")
    return 0 if jobs else 1


if __name__ == "__main__":
    raise SystemExit(main())
