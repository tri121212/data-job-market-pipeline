-- Schemas created on first Postgres boot.
-- raw       : landing zone written by the ingestion loader (JSONB payloads)
-- analytics : dbt target schema for staging/marts (dbt will create its own too)
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;
