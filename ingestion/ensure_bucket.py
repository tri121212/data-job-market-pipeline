"""Create the raw bucket in the local S3-compatible object store (idempotent).

Usage:
    python -m ingestion.ensure_bucket
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from dotenv import load_dotenv

load_dotenv()


def ensure_bucket(bucket: str | None = None) -> str:
    endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
    bucket = bucket or os.getenv("S3_BUCKET", "raw")

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )

    try:
        s3.create_bucket(Bucket=bucket)
        print(f"created bucket: {bucket}")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            print(f"bucket already exists: {bucket}")
        else:
            raise
    return bucket


def main() -> int:
    try:
        ensure_bucket()
    except EndpointConnectionError:
        print(
            "Cannot reach the object store. Is the stack running? Try: make up",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
