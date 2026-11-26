"""Crawler tests: filtering, dedupe, reject audit trail and resume state."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from ingestion import scrape
from ingestion.config import Settings

FIXTURES = Path(__file__).parent.parent / "docs" / "samples"
IT_HTML = gzip.decompress((FIXTURES / "topdev_job_it.html.gz").read_bytes()).decode()
BANK_HTML = gzip.decompress((FIXTURES / "topdev_job_bank.html.gz").read_bytes()).decode()


class FakeStore:
    """In-memory stand-in for ObjectStore."""

    def __init__(self) -> None:
        self.objects: dict[str, object] = {}

    def put_jsonl(self, key: str, rows: list[dict]) -> None:
        self.objects[key] = list(rows)

    def put_json(self, key: str, payload: dict) -> None:
        self.objects[key] = payload

    def put_html(self, key: str, html: str) -> None:
        self.objects[key] = html

    def get_json(self, key: str):
        return self.objects.get(key)


@pytest.fixture()
def settings() -> Settings:
    return Settings(request_delay_seconds=0, max_pages_per_run=2)


def test_crawl_page_keeps_it_jobs_and_records_rejects(monkeypatch, settings):
    store = FakeStore()
    monkeypatch.setattr(scrape, "sitemap_job_urls", lambda page, session: ["u-it", "u-bank"])
    monkeypatch.setattr(scrape, "fetch", lambda url, session: IT_HTML if url == "u-it" else BANK_HTML)

    result = scrape.crawl_page(
        page=1, dt="2026-11-26", store=store, session=object(), settings=settings, seen_ids=set()
    )

    assert result.ok is True
    assert result.jobs_seen == 2
    assert result.jobs_it == 1
    assert result.jobs_rejected == 1

    jobs = store.objects["jobs/dt=2026-11-26/page=001.jsonl"]
    assert len(jobs) == 1
    assert jobs[0]["source_id"] == "2138855"
    assert jobs[0]["filter_reason"] == "match:sharepoint"
    assert jobs[0]["dt"] == "2026-11-26"
    assert jobs[0]["job"]["title"].startswith("Chuyên viên Ứng dụng")

    rejects = store.objects["_rejects/dt=2026-11-26/page=001.jsonl"]
    assert len(rejects) == 1
    assert rejects[0]["reason"] == "no_it_keyword"

    assert "html/dt=2026-11-26/2138855.html.gz" in store.objects


def test_duplicate_ids_are_skipped_across_pages(monkeypatch, settings):
    store = FakeStore()
    seen: set[str] = set()
    monkeypatch.setattr(scrape, "sitemap_job_urls", lambda page, session: ["u-it"])
    monkeypatch.setattr(scrape, "fetch", lambda url, session: IT_HTML)

    first = scrape.crawl_page(
        page=1, dt="2026-11-26", store=store, session=object(), settings=settings, seen_ids=seen
    )
    second = scrape.crawl_page(
        page=2, dt="2026-11-26", store=store, session=object(), settings=settings, seen_ids=seen
    )

    assert first.jobs_it == 1
    assert second.jobs_it == 0
    assert second.jobs_duplicate == 1


def test_sitemap_failure_marks_page_failed(monkeypatch, settings):
    import requests

    store = FakeStore()

    def boom(page, session):
        raise requests.RequestException("network down")

    monkeypatch.setattr(scrape, "sitemap_job_urls", boom)

    result = scrape.crawl_page(
        page=1, dt="2026-11-26", store=store, session=object(), settings=settings, seen_ids=set()
    )
    assert result.ok is False
    assert result.warnings and "failed" in result.warnings[0]


def test_state_roundtrip_and_resume(settings):
    store = FakeStore()
    state = scrape.load_state(store, "2026-11-26")
    assert state["done_pages"] == []

    state["done_pages"] = [1, 2]
    scrape.save_state(store, "2026-11-26", state)

    reloaded = scrape.load_state(store, "2026-11-26")
    assert reloaded["done_pages"] == [1, 2]
    assert reloaded["updated_at"] is not None


def test_slug_prefilter_skips_network_call(monkeypatch, settings):
    store = FakeStore()
    calls: list[str] = []

    monkeypatch.setattr(
        scrape,
        "sitemap_job_urls",
        lambda page, session: ["https://topdev.vn/detail-jobs/nhan-vien-kinh-doanh-123"],
    )
    monkeypatch.setattr(scrape, "fetch", lambda url, session: calls.append(url) or IT_HTML)

    result = scrape.crawl_page(
        page=1, dt="2026-11-26", store=store, session=object(), settings=settings, seen_ids=set()
    )

    assert calls == [], "non-IT slug must not trigger a job page request"
    assert result.jobs_skipped == 1
    assert result.jobs_it == 0
