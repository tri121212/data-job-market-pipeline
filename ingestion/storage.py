"""S3/MinIO access layer and the object-key conventions for the raw zone.

Why a wrapper: the rest of the code should say "store this job" rather than
"boto3 ... put_object ... Body=json.dumps(...)". One place to change when we
move from MinIO to S3, and one place to test.

Layout produced:
    s3://raw/jobs/dt=YYYY-MM-DD/page=NNN.jsonl
    s3://raw/html/dt=YYYY-MM-DD/<source_id>.html.gz
    s3://raw/_state/dt=YYYY-MM-DD/pages_done.json
    s3://raw/_meta/dt=YYYY-MM-DD/run_summary.json
"""

from __future__ import annotations

import gzip
import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .config import Settings, get_settings


# --------------------------------------------------------------------------- #
# key conventions (pure functions -> easy to unit test)
# --------------------------------------------------------------------------- #
def jobs_key(dt: str, page: int) -> str:
    return f"jobs/dt={dt}/page={page:03d}.jsonl"


def html_key(dt: str, source_id: str) -> str:
    return f"html/dt={dt}/{source_id}.html.gz"


def state_key(dt: str) -> str:
    return f"_state/dt={dt}/pages_done.json"


def meta_key(dt: str) -> str:
    return f"_meta/dt={dt}/run_summary.json"


def rejects_key(dt: str, page: int) -> str:
    """Titles rejected by the IT filter, kept for auditing the rules."""
    return f"_rejects/dt={dt}/page={page:03d}.jsonl"


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
class ObjectStore:
    """Thin, testable wrapper around an S3-compatible bucket."""

    def __init__(self, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ObjectStore:
        cfg = settings or get_settings()
        client = boto3.client(
            "s3",
            endpoint_url=cfg.s3_endpoint,
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
            region_name=cfg.aws_region,
        )
        return cls(bucket=cfg.s3_bucket, client=client)

    # -- writes ------------------------------------------------------------- #
    def put_text(self, key: str, body: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body.encode("utf-8"))

    def put_bytes(self, key: str, body: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body)

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self.put_text(key, json.dumps(payload, ensure_ascii=False, indent=2))

    def put_jsonl(self, key: str, rows: list[dict[str, Any]]) -> None:
        body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        if body:
            body += "\n"
        self.put_text(key, body)

    def put_html(self, key: str, html: str) -> None:
        self.put_bytes(key, gzip.compress(html.encode("utf-8")))

    # -- reads -------------------------------------------------------------- #
    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                return False
            raise

    def get_text(self, key: str) -> str | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                return None
            raise
        return response["Body"].read().decode("utf-8")

    def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                return None
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under a prefix (used to reprocess one day)."""
        keys = self.list_keys(prefix)
        for start in range(0, len(keys), 1000):
            batch = [{"Key": key} for key in keys[start : start + 1000]]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
        return len(keys)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)
