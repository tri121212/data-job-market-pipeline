"""Smoke test: the local environment can import every runtime dependency.

Real pipeline tests (parsers, loaders) arrive on Day 5. This keeps CI green
from day one and catches a broken virtualenv early.
"""


def test_runtime_dependencies_import() -> None:
    import boto3  # noqa: F401
    import bs4  # noqa: F401
    import psycopg  # noqa: F401
    import pydantic_settings  # noqa: F401
    import requests  # noqa: F401
    import structlog  # noqa: F401
