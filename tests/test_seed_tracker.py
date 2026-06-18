"""
tests/test_seed_tracker.py
Coverage for src/etl/seed_tracker.py — seeds skilled_tracker_clients
from the EVV Billing Log Excel file.

Tier 2 — requires the EVV Billing Log file on disk.
Tests are automatically skipped if the file is not present.

Every assertion includes:
  FAIL    — what broke in plain English
  CAUSE   — most likely reasons, ordered by probability
  ACTION  — exact steps the operator or developer takes next
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


def _evv_file():
    """Return the EVV tracker file path, or None if not configured."""
    try:
        from src.config import cfg
        return getattr(cfg, "evv_tracker_file", None)
    except Exception:
        return None


class TestSeedTrackerClients:
    def test_inserts_rows(self):
        """seed_tracker_clients() inserts at least one row into skilled_tracker_clients."""
        evv_file = _evv_file()
        if evv_file is None or not Path(evv_file).exists():
            pytest.skip("EVV Billing Log file not available in this environment")
        conn = _db()
        seed_tracker_clients(conn, evv_file)
        count = conn.execute("SELECT COUNT(*) FROM skilled_tracker_clients").fetchone()[0]
        assert count > 0, (
            "FAIL — seed_tracker_clients() inserted 0 rows into skilled_tracker_clients.\n"
            f"File: {evv_file}\n"
            "CAUSE — check in this order:\n"
            "  1. The EVV Billing Log file exists but contains no data rows "
            "(only headers, or a blank template was placed in the input folder).\n"
            "  2. The sheet layout has changed — the parser cannot find the expected columns.\n"
            "  3. A filter is excluding all rows (e.g. all rows have a status that is filtered out).\n"
            "ACTION:\n"
            "  1. Open the EVV Billing Log file and confirm it has data rows below the header.\n"
            "  2. If the file looks correct, flag to developer — the column positions \n"
            "     or sheet name expected by seed_tracker.py may have changed."
        )

    def test_idempotent_no_duplicates(self):
        """Running seed_tracker_clients() twice produces the same row count (no duplicates)."""
        evv_file = _evv_file()
        if evv_file is None or not Path(evv_file).exists():
            pytest.skip("EVV Billing Log file not available in this environment")
        conn = _db()
        seed_tracker_clients(conn, evv_file)
        count1 = conn.execute("SELECT COUNT(*) FROM skilled_tracker_clients").fetchone()[0]
        seed_tracker_clients(conn, evv_file)
        count2 = conn.execute("SELECT COUNT(*) FROM skilled_tracker_clients").fetchone()[0]
        assert count1 == count2, (
            f"FAIL — Running seed_tracker_clients() twice created duplicate rows.\n"
            f"First run inserted {count1} rows. Second run produced {count2} rows "
            f"(delta = {count2 - count1}).\n"
            "CAUSE: The seed function is using INSERT instead of INSERT OR REPLACE / UPSERT. "
            "Re-ingesting the same EVV file will corrupt the billing tracker with "
            "duplicate client entries.\n"
            "ACTION: Flag to developer immediately. "
            "Do NOT re-ingest the EVV file again until this is fixed. "
            "This is a code bug in seed_tracker.py — the operator cannot resolve it."
        )

    def test_missing_file_raises(self, tmp_path):
        """Passing a non-existent path raises a meaningful error (not a silent failure)."""
        conn = _db()
        missing = tmp_path / "does_not_exist.xlsx"
        try:
            seed_tracker_clients(conn, missing)
            # If no exception was raised, the function silently swallowed the error
            raise AssertionError(
                "FAIL — seed_tracker_clients() did not raise an error when given a "
                "non-existent file path.\n"
                f"Path tested: {missing}\n"
                "CAUSE: The function silently ignores missing files instead of raising "
                "FileNotFoundError or a clear ValueError.\n"
                "ACTION: Flag to developer. A missing EVV file should always surface a "
                "clear error message so the operator knows the file was not found, "
                "rather than silently seeding 0 rows with no feedback."
            )
        except (FileNotFoundError, OSError, ValueError):
            # Expected — any of these is an acceptable meaningful error
            pass
