-- Landing table for raw job postings (one row per posting).
-- Written by ingestion/load.py; read by dbt staging models.
--
-- Design:
--   source_id  natural key from the source (URL tail), stable across re-crawls
--   payload    the full parsed job as JSONB, so dbt can re-shape without re-crawling
--   first_seen / last_seen  track when a posting appeared and was last observed
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
