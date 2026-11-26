"""Tests for the TopDev JobPosting parser, using real captured HTML fixtures."""

from __future__ import annotations

import gzip
from pathlib import Path

from ingestion.explore import parse_jobposting

FIXTURES = Path(__file__).parent.parent / "docs" / "samples"


def load_fixture(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8", "ignore")


def test_parses_salary_range() -> None:
    job = parse_jobposting(load_fixture("topdev_job_bank.html.gz"))
    assert job is not None
    assert job["salary_min"] == 3_000_000
    assert job["salary_max"] == 16_000_000
    assert job["currency"] == "VND"
    assert job["salary_unit"] == "MONTH"
    assert job["is_salary_negotiable"] is False


def test_parses_negotiable_salary() -> None:
    job = parse_jobposting(load_fixture("topdev_job_it.html.gz"))
    assert job is not None
    assert job["salary_min"] is None
    assert job["salary_max"] is None
    assert job["is_salary_negotiable"] is True
    assert job["currency"] == "VND"


def test_parses_identity_and_skills() -> None:
    job = parse_jobposting(load_fixture("topdev_job_it.html.gz"))
    assert job is not None
    assert job["source"] == "topdev"
    assert job["source_id"] == "2138855"
    assert job["company_id"] == "97179"
    assert job["title"].startswith("Chuyên viên Ứng dụng Microsoft 365")
    assert job["skills"] == ["Sharepoint", "Microsoft 365"]
    assert job["location_region"] == "Hồ Chí Minh"
    assert job["location_country"] == "VN"
    assert job["posted_at"] == "2026-11-24"


def test_description_is_textualized() -> None:
    job = parse_jobposting(load_fixture("topdev_job_bank.html.gz"))
    assert job is not None
    assert "<" not in job["description_text"]
    assert len(job["description_text"]) > 100


def test_returns_none_without_jobposting() -> None:
    assert parse_jobposting("<html><body>no structured data</body></html>") is None


def test_job_id_is_taken_from_url_tail() -> None:
    from ingestion.explore import job_id_from_url

    assert job_id_from_url("https://topdev.vn/detail-jobs/a-b-c-2138855") == "2138855"
    assert job_id_from_url("https://topdev.vn/detail-jobs/x-123?src=home") == "123"
    assert job_id_from_url(None) is None
    assert job_id_from_url("https://topdev.vn/no-id-here") is None
