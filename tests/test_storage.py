"""Key-layout tests: the object naming is a contract with the loader (Day 4)."""

from ingestion.storage import html_key, jobs_key, meta_key, state_key


def test_jobs_key_is_zero_padded_and_partitioned_by_day() -> None:
    assert jobs_key("2026-11-26", 1) == "jobs/dt=2026-11-26/page=001.jsonl"
    assert jobs_key("2026-11-26", 20) == "jobs/dt=2026-11-26/page=020.jsonl"


def test_html_key_keeps_source_id() -> None:
    assert html_key("2026-11-26", "97179") == "html/dt=2026-11-26/97179.html.gz"


def test_state_and_meta_keys() -> None:
    assert state_key("2026-11-26") == "_state/dt=2026-11-26/pages_done.json"
    assert meta_key("2026-11-26") == "_meta/dt=2026-11-26/run_summary.json"
