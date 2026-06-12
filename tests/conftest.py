"""Shared fixtures for test suite."""

import tempfile
from pathlib import Path

import pytest

from src.db.connection import get_conn


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """Run the pipeline once and reuse for all tests."""
    from src.etl.pipeline import run_pipeline

    db = tmp_path_factory.mktemp("data") / "test.duckdb"
    run_pipeline(db_path=db)
    return db


@pytest.fixture(scope="session")
def conn(db_path):
    """Persistent read-only connection for query tests."""
    c = get_conn(db_path, read_only=True)
    yield c
    c.close()
