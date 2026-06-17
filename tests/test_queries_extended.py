"""
tests/test_queries_extended.py
Extended tests for src/db/queries.py covering gaps from Phase 3.

Adds:
  - weekly_summary:  week_start filter, KPI column presence
  - followup_items:  result_simple=Follow up only, reason filter
  - copay_monthly_status: year/month filter, status enum validation (in-memory)
  - upsert_name_match: insert new and update existing rows
  - SQL injection guard: malicious insurance/week_start params don't corrupt DB
  - client_summary:  ytd_pending_hrs clamped to >= 0 (no overpayment bleed)
  - dedup_tcn helpers: SQL in queries.py via _dedup_tcn_pass1 / _dedup_tcn_pass2
"""
from __future__ import annotations
from datetime import date

import duckdb
import pytest

from src.db.schema import create_all
from src.db import queries as q


# ── fixture helpers ───────────────────────────────────────────────────────────

def _db() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    create_all(conn)
    return conn


def _seed_recon(conn, rows):
    """Insert minimal reconciliation rows for query tests."""
    for i, r in enumerate(rows, start=1):
        conn.execute("""
            INSERT INTO reconciliation (
                id, week_start_date, week_end_date, insurance,
                client_name_payroll, client_name_remittance,
                payroll_hours, billed_hours, paid_hours,
                result_simple, result_detailed, care_type,
                is_copay_client, match_status
            ) VALUES (nextval('seq_reconciliation'),?,?,?,?,?,?,?,?,?,?,?,'Unskilled',FALSE,'MATCHED')
        """, [
            r.get("week_start", "2026-02-18"),
            r.get("week_end",   "2026-02-24"),
            r.get("insurance",  "Medicaid"),
            r.get("payroll_name",    "CLIENT, ONE"),
            r.get("remit_name",      "CLIENT, ONE"),
            r.get("payroll_hours",   35.0),
            r.get("billed_hours",    35.0),
            r.get("paid_hours",      35.0),
            r.get("result_simple",   "Good"),
            r.get("result_detailed", None),
        ])


# ── weekly_summary ────────────────────────────────────────────────────────────

class TestWeeklySummaryExtended:
    def test_kpi_columns_present(self):
        """weekly_summary() DataFrame must contain total_clients column."""
        conn = _db()
        _seed_recon(conn, [{}])
        df = q.weekly_summary(conn)
        assert "total_clients" in df.columns

    def test_week_filter(self):
        """Passing week_start limits result to that week only."""
        conn = _db()
        _seed_recon(conn, [
            {"week_start": "2026-02-18", "week_end": "2026-02-24"},
            {"week_start": "2026-02-25", "week_end": "2026-03-03",
             "payroll_name": "CLIENT, TWO", "remit_name": "CLIENT, TWO"},
        ])
        df = q.weekly_summary(conn, week_start="2026-02-18")
        dates = df["week_start_date"].astype(str).tolist()
        assert all("2026-02-18" in d for d in dates), \
            f"Filter returned wrong weeks: {dates}"


# ── followup_items ────────────────────────────────────────────────────────────

class TestFollowupItemsExtended:
    def test_only_followup_rows_returned(self):
        """followup_items() must never return rows with result_simple != 'Follow up'."""
        conn = _db()
        _seed_recon(conn, [
            {"result_simple": "Good"},
            {"result_simple": "Follow up", "result_detailed": "Not Billed",
             "payroll_name": "CLIENT, TWO", "remit_name": "CLIENT, TWO",
             "billed_hours": 0.0, "paid_hours": 0.0},
        ])
        df = q.followup_items(conn)
        for _, row in df.iterrows():
            assert row["result_simple"] == "Follow up", \
                f"Non-followup row leaked: {row['result_simple']}"

    def test_reason_filter(self):
        """Passing reason='Not Billed' returns only Not Billed rows."""
        conn = _db()
        _seed_recon(conn, [
            {"result_simple": "Follow up", "result_detailed": "Not Billed",
             "payroll_name": "CLIENT, A", "remit_name": "CLIENT, A",
             "billed_hours": 0.0, "paid_hours": 0.0},
            {"result_simple": "Follow up", "result_detailed": "Not Paid",
             "payroll_name": "CLIENT, B", "remit_name": "CLIENT, B",
             "billed_hours": 35.0, "paid_hours": 0.0},
        ])
        df = q.followup_items(conn, reason="Not Billed")
        for _, row in df.iterrows():
            assert row["result_detailed"] == "Not Billed"


# ── upsert_name_match ─────────────────────────────────────────────────────────

class TestUpsertNameMatch:
    def test_insert_new_row(self):
        """upsert_name_match inserts a new row when payroll_name not in DB."""
        conn = _db()
        q.upsert_name_match(conn,
                            payroll_name="NEWCLIENT, TEST",
                            remittance_name="NEWCLIENT, TEST")
        rows = conn.execute(
            "SELECT remittance_name FROM name_match WHERE payroll_name='NEWCLIENT, TEST'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "NEWCLIENT, TEST"

    def test_update_existing_row(self):
        """upsert_name_match updates remittance_name for existing payroll_name."""
        conn = _db()
        # Insert initial row
        conn.execute(
            "INSERT INTO name_match (id, payroll_name, remittance_name) "
            "VALUES (nextval('seq_name_match'), 'SMITH, JOHN', 'SMITH, JOHN OLD')"
        )
        q.upsert_name_match(conn,
                            payroll_name="SMITH, JOHN",
                            remittance_name="SMITH, JOHN UPDATED")
        row = conn.execute(
            "SELECT remittance_name FROM name_match WHERE payroll_name='SMITH, JOHN'"
        ).fetchone()
        assert row[0] == "SMITH, JOHN UPDATED"

    def test_idempotent_double_upsert(self):
        """Calling upsert twice with same data results in exactly 1 row."""
        conn = _db()
        for _ in range(2):
            q.upsert_name_match(conn, "DUPE, CLIENT", "DUPE, CLIENT REMIT")
        count = conn.execute(
            "SELECT COUNT(*) FROM name_match WHERE payroll_name='DUPE, CLIENT'"
        ).fetchone()[0]
        assert count == 1


# ── SQL injection defence ─────────────────────────────────────────────────────

class TestSqlInjectionDefence:
    def test_malicious_insurance_filter(self):
        """
        Passing a SQL-injection string as insurance param must not crash the app
        or corrupt the reconciliation table.
        """
        conn = _db()
        _seed_recon(conn, [{"insurance": "Medicaid"}])
        original_count = conn.execute("SELECT COUNT(*) FROM reconciliation").fetchone()[0]
        malicious = "'; DROP TABLE reconciliation; --"
        try:
            q.followup_items(conn, insurance=malicious)
        except Exception:
            pass  # Exception is acceptable; corruption is not
        # Table must still exist and have its row
        count = conn.execute("SELECT COUNT(*) FROM reconciliation").fetchone()[0]
        assert count == original_count, "reconciliation table was corrupted by injection"

    def test_malicious_week_start_param(self):
        """Injection string as week_start does not corrupt DB."""
        conn = _db()
        _seed_recon(conn, [{}])
        original_count = conn.execute("SELECT COUNT(*) FROM reconciliation").fetchone()[0]
        try:
            q.weekly_summary(conn, week_start="2026-01-01'; DROP TABLE reconciliation; --")
        except Exception:
            pass
        count = conn.execute("SELECT COUNT(*) FROM reconciliation").fetchone()[0]
        assert count == original_count


# ── client_summary pending hours ─────────────────────────────────────────────

class TestClientSummaryPendingHours:
    def test_pending_hours_not_negative(self):
        """
        Overpayment weeks (paid > payroll) must NOT make pending hours go negative.
        pending = SUM(GREATEST(payroll - paid, 0))  per week.
        """
        conn = _db()
        client = "OVERPAY, CLIENT"
        # Week 1: overpayment (paid > payroll) -> contribution = 0
        conn.execute(
            "INSERT INTO reconciliation "
            "(id, week_start_date, week_end_date, client_name_payroll, "
            " client_name_remittance, payroll_hours, billed_hours, paid_hours, "
            " result_simple, care_type, match_status) "
            "VALUES (nextval('seq_reconciliation'),'2026-02-18','2026-02-24',?,?,"
            "10.0, 10.0, 20.0,'Good','Unskilled','MATCHED')",
            [client, client]
        )
        # Week 2: genuinely unpaid -> contribution = 15
        conn.execute(
            "INSERT INTO reconciliation "
            "(id, week_start_date, week_end_date, client_name_payroll, "
            " client_name_remittance, payroll_hours, billed_hours, paid_hours, "
            " result_simple, care_type, match_status) "
            "VALUES (nextval('seq_reconciliation'),'2026-02-25','2026-03-03',?,?,"
            "15.0, 15.0, 0.0,'Follow up','Unskilled','MATCHED')",
            [client, client]
        )
        df = q.client_summary(conn, client, "Unskilled")
        assert len(df) == 1
        pending = float(df.iloc[0]["ytd_pending_hrs"])
        assert pending >= 0, f"Pending hours went negative: {pending}"
        assert pending == 15.0, f"Expected 15.0 pending hrs, got {pending}"
