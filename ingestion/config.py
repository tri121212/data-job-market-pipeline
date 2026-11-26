"""Central configuration, loaded from environment / .env.

Keeping every tunable here means the crawler has no magic numbers and the
same code runs locally (MinIO) or against real S3 by changing env only.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # object storage (MinIO locally, S3 in the cloud)
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "raw"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"
    aws_region: str = "us-east-1"

    # warehouse (Postgres). Aliases keep the existing docker-compose env names.
    pg_host: str = Field("localhost", validation_alias="POSTGRES_HOST")
    pg_port: int = Field(5433, validation_alias="POSTGRES_PORT")
    pg_db: str = Field("jobmarket", validation_alias="POSTGRES_DB")
    pg_user: str = Field("djm", validation_alias="POSTGRES_USER")
    pg_password: str = Field("djm_dev_password", validation_alias="POSTGRES_PASSWORD")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    # crawl behaviour
    request_delay_seconds: float = 1.0
    max_pages_per_run: int = 20
    sitemap_page_url: str = "https://topdev.vn/sitemap/jobs_desc_en_page_{page}.xml"


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (cached: env is read once per process)."""
    return Settings()
