"""Unit tests for the loader's pure helpers (no database needed)."""

from __future__ import annotations

import json
from datetime import datetime

from ingestion.load import dates_in_bucket, parse_jsonl, record_params

SAMPLE = {
    "source": "topdev",
    "source_id": "2138855",
    "dt": "2026-11-26",
    "crawled_at": "2026-11-26T12:10:00+07:00",
    "is_it_job": True,
    "filter_reason": "match:sharepoint",
    "job": {
        "title": "Chuyên viên Ứng dụng Microsoft 365",
        "company": "T.N.T",
        "company_id": "97179",
        "skills": ["Sharepoint"],
    },
}


def test_parse_jsonl_ignores_blank_lines() -> None:
    text = json.dumps(SAMPLE) + "\n\n" + json.dumps(SAMPLE) + "\n"
    assert len(parse_jsonl(text)) == 2


def test_record_params_maps_every_column() -> None:
    params = record_params(SAMPLE)
    assert params["source_id"] == "2138855"
    assert params["dt"] == "2026-11-26"
    assert params["company_id"] == "97179"
    assert params["title"].startswith("Chuyên viên")
    assert params["is_it_job"] is True
    assert params["filter_reason"] == "match:sharepoint"
    assert params["crawled_at"] == datetime.fromisoformat("2026-11-26T12:10:00+07:00")


def test_dates_in_bucket_dedupes_and_sorts() -> None:
    keys = [
        "jobs/dt=2026-11-26/page=001.jsonl",
        "jobs/dt=2026-11-26/page=002.jsonl",
        "jobs/dt=2026-11-25/page=001.jsonl",
    ]
    assert dates_in_bucket(keys) == ["2026-11-25", "2026-11-26"]
