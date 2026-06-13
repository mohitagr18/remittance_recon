"""Shared fixtures for test suite."""

from pathlib import Path

import pytest

from src.db.connection import get_persistent_conn


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """Run the pipeline once and reuse for all tests."""
    from src.etl.pipeline import run_pipeline
    from src.config import cfg

    db = tmp_path_factory.mktemp("data") / "test.duckdb"
    run_pipeline(
        db_path=db,
        payroll_path=cfg.payroll_file,
        remittance_path=cfg.remittance_file,
    )
    return db


@pytest.fixture(scope="session")
def conn(db_path):
    """Persistent read-only connection for query tests."""
    c = get_persistent_conn(db_path)
    yield c
    c.close()
