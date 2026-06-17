"""
tests/test_seed_tracker.py
Coverage for src/etl/seed_tracker.py — seeds skilled_tracker_clients
from the EVV Billing Log Excel file.

Covers:
  - seed_tracker_clients() inserts rows into skilled_tracker_clients
  - Running seed twice does NOT duplicate rows (idempotency)
  - Missing file raises a meaningful error
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from src.db.schema import create_all
from src.etl.seed_tracker import seed_tracker_clients


def _db() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    create_all(conn)
    return conn


class TestSeedTrackerClients:
    def test_inserts_rows(self):
        """seed_tracker_clients inserts at least one row into skilled_tracker_clients."""
        from src.config import cfg
        evv_file = getattr(cfg, "evv_tracker_file", None)
        if evv_file is None or not Path(evv_file).exists():
            pytest.skip("EVV Billing Log file not available in this environment")
        conn = _db()
        seed_tracker_clients(conn, evv_file)
        count = conn.execute("SELECT COUNT(*) FROM skilled_tracker_clients").fetchone()[0]
        assert count > 0, "seed_tracker_clients inserted 0 rows"

    def test_idempotent_no_duplicates(self):
        """Running seed_tracker_clients twice produces the same row count."""
        from src.config import cfg
        evv_file = getattr(cfg, "evv_tracker_file", None)
        if evv_file is None or not Path(evv_file).exists():
            pytest.skip("EVV Billing Log file not available in this environment")
        conn = _db()
        seed_tracker_clients(conn, evv_file)
        count1 = conn.execute("SELECT COUNT(*) FROM skilled_tracker_clients").fetchone()[0]
        seed_tracker_clients(conn, evv_file)
        count2 = conn.execute("SELECT COUNT(*) FROM skilled_tracker_clients").fetchone()[0]
        assert count1 == count2, (
            f"Duplicate rows on second seed: {count1} -> {count2}"
        )

    def test_missing_file_raises(self, tmp_path):
        """Passing a non-existent path raises FileNotFoundError or similar."""
        conn = _db()
        missing = tmp_path / "does_not_exist.xlsx"
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            seed_tracker_clients(conn, missing)
