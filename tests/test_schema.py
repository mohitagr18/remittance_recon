"""
tests/test_schema.py
Coverage for src/db/schema.py and src/db/connection.py.

Covers: create_all idempotency, all tables/sequences present,
required column sets, get_conn context manager, get_persistent_conn,
read_only enforcement.
"""
from __future__ import annotations
from pathlib import Path

import duckdb
import pytest

from src.db.connection import get_conn, get_persistent_conn
from src.db.schema import create_all

EXPECTED_TABLES = {
    "name_match", "copay_clients", "employees", "payroll", "remittance",
    "reconciliation", "ingested_files", "rebill_tracker", "review_actions",
    "skilled_tracker_clients", "skilled_tracker_comments",
    "tracker_validation_runs",
}
EXPECTED_SEQUENCES = {
    "seq_name_match", "seq_copay_clients", "seq_employees", "seq_payroll",
    "seq_remittance", "seq_reconciliation", "seq_rebill_tracker",
    "seq_review_actions", "seq_ingested_files",
    "seq_skilled_tracker_clients", "seq_skilled_tracker_comments",
    "seq_tracker_validation_runs",
}


def _fresh_db():
    conn = duckdb.connect(":memory:")
    create_all(conn)
    return conn


class TestCreateAll:
    def test_idempotent(self):
        """Running create_all twice must not raise."""
        conn = duckdb.connect(":memory:")
        create_all(conn)
        create_all(conn)

    def test_all_tables_exist(self):
        conn = _fresh_db()
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        existing = {r[0] for r in rows}
        for t in EXPECTED_TABLES:
            assert t in existing, f"Missing table: {t}"

    def test_reconciliation_columns(self):
        conn = _fresh_db()
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='reconciliation'"
        ).fetchall()}
        for c in ["id","week_start_date","week_end_date","insurance",
                  "client_name_payroll","client_name_remittance","payroll_hours",
                  "billed_hours","paid_hours","result_simple","result_detailed",
                  "is_copay_client","match_status","care_type"]:
            assert c in cols, f"reconciliation missing: {c}"

    def test_copay_clients_columns(self):
        conn = _fresh_db()
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='copay_clients'"
        ).fetchall()}
        for c in ["id","client_name","copay_amount","is_active",
                  "effective_from","effective_to","updated_at"]:
            assert c in cols, f"copay_clients missing: {c}"

    def test_remittance_columns(self):
        conn = _fresh_db()
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='remittance'"
        ).fetchall()}
        for c in ["id","tcn","batch","payment_date","transaction_type",
                  "charge_amount","payment_amount","billed_hours","paid_hours",
                  "client_name_combined","first_dos","is_latest"]:
            assert c in cols, f"remittance missing: {c}"

    def test_sequences_usable(self):
        conn = _fresh_db()
        for seq in EXPECTED_SEQUENCES:
            val = conn.execute(f"SELECT nextval('{seq}')").fetchone()[0]
            assert isinstance(val, int), f"nextval({seq}) not int"

    def test_deactivated_from_migration_column(self):
        """Migration adds deactivated_from to skilled_tracker_clients."""
        conn = _fresh_db()
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='skilled_tracker_clients'"
        ).fetchall()}
        assert "deactivated_from" in cols


class TestGetConn:
    def test_yields_connection(self, tmp_path):
        db = tmp_path / "t.duckdb"
        with get_conn(db) as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1

    def test_closes_on_exit(self, tmp_path):
        db = tmp_path / "t.duckdb"
        with get_conn(db) as conn:
            captured = conn
        with pytest.raises(Exception):
            captured.execute("SELECT 1")

    def test_read_only_rejects_writes(self, tmp_path):
        db = tmp_path / "t.duckdb"
        with get_conn(db) as conn:
            create_all(conn)
        with get_conn(db, read_only=True) as conn:
            with pytest.raises(Exception):
                conn.execute("INSERT INTO name_match (id, payroll_name) VALUES (1, 'X')")


class TestGetPersistentConn:
    def test_creates_db_file(self, tmp_path):
        db = tmp_path / "sub" / "new.duckdb"
        assert not db.exists()
        conn = get_persistent_conn(db)
        conn.execute("SELECT 42")
        conn.close()
        assert db.exists()

    def test_returns_open_connection(self, tmp_path):
        db = tmp_path / "t.duckdb"
        conn = get_persistent_conn(db)
        try:
            assert conn.execute("SELECT 99").fetchone()[0] == 99
        finally:
            conn.close()
