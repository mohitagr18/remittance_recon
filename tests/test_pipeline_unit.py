"""
tests/test_pipeline_unit.py
Unit tests for stateless helpers and DB-write functions in src/etl/pipeline.py.
All DB interactions use an in-memory schema — no real Excel files required.

Covers:
  - get_week_start() / get_week_end() — Wednesday calendar alignment
  - determine_care_type()             — Skilled vs Unskilled
  - _normalize_insurance()            — remittance→payroll name mapping
  - _normalize_client_key()           — key normalisation (strip commas, uppercase)
  - _dedup_tcn_is_latest()            — Pass 1 (same TCN) and Pass 2 (rebill)
  - _write_payroll_incremental()      — idempotency (same record twice = 1 row)
"""
from __future__ import annotations
from datetime import date

import duckdb
import pytest

from src.db.schema import create_all
from src.etl.pipeline import (
    _normalize_client_key,
    _normalize_insurance,
    _dedup_tcn_is_latest,
    _write_payroll_incremental,
    determine_care_type,
    get_week_end,
    get_week_start,
)


def _db():
    conn = duckdb.connect(":memory:")
    create_all(conn)
    return conn


# ── get_week_start ────────────────────────────────────────────────────────────

class TestGetWeekStart:
    @pytest.mark.parametrize("d,expected", [
        (date(2026, 2, 18), date(2026, 2, 18)),  # Wednesday itself
        (date(2026, 2, 19), date(2026, 2, 18)),  # Thursday
        (date(2026, 2, 20), date(2026, 2, 18)),  # Friday
        (date(2026, 2, 21), date(2026, 2, 18)),  # Saturday
        (date(2026, 2, 22), date(2026, 2, 18)),  # Sunday
        (date(2026, 2, 23), date(2026, 2, 18)),  # Monday
        (date(2026, 2, 24), date(2026, 2, 18)),  # Tuesday
    ])
    def test_alignment(self, d, expected):
        assert get_week_start(d) == expected

    def test_wednesday_is_own_start(self):
        d = date(2026, 6, 17)   # known Wednesday
        assert get_week_start(d) == d

    def test_tuesday_falls_in_prior_week(self):
        tuesday = date(2026, 6, 16)
        assert get_week_start(tuesday) == date(2026, 6, 10)


class TestGetWeekEnd:
    def test_six_days_after_start(self):
        assert get_week_end(date(2026, 2, 18)) == date(2026, 2, 24)

    def test_end_is_always_tuesday(self):
        for d in [date(2026, 1, 7), date(2026, 3, 18), date(2026, 6, 3)]:
            end = get_week_end(get_week_start(d))
            assert end.weekday() == 1, f"Expected Tue, got {end.strftime('%A')} ({end})"


# ── determine_care_type ───────────────────────────────────────────────────────

class TestDetermineCareType:
    def test_lpn_in_name_is_skilled(self):
        assert determine_care_type("SMITH, JANE LPN", "Medicaid") == "Skilled"

    def test_rn_in_name_is_skilled(self):
        assert determine_care_type("DOE, JOHN RN", "Sentara") == "Skilled"

    def test_pdn_in_insurance_is_skilled(self):
        assert determine_care_type("JONES, BOB", "Medicaid & PDN") == "Skilled"

    def test_pdn_lowercase_in_insurance(self):
        assert determine_care_type("JONES, BOB", "sentara & pdn") == "Skilled"

    def test_pca_is_unskilled(self):
        assert determine_care_type("JOHNSON, MARY PCA", "Medicaid") == "Unskilled"

    def test_plain_name_is_unskilled(self):
        assert determine_care_type("WILLIAMS, LENA", "Medicaid") == "Unskilled"

    def test_none_name_is_unskilled(self):
        assert determine_care_type(None, "Medicaid") == "Unskilled"

    def test_none_insurance_is_unskilled(self):
        assert determine_care_type("JONES, BOB", None) == "Unskilled"

    def test_both_none_is_unskilled(self):
        assert determine_care_type(None, None) == "Unskilled"


# ── _normalize_insurance ──────────────────────────────────────────────────────

class TestNormalizeInsurance:
    def test_united_to_uhc(self):
        assert _normalize_insurance("United") == "UHC"

    def test_medicaid_pdn_to_medicaid(self):
        assert _normalize_insurance("Medicaid & PDN") == "Medicaid"

    def test_sentara_pdn_to_sentara(self):
        assert _normalize_insurance("Sentara & PDN") == "Sentara"

    def test_unknown_passthrough(self):
        assert _normalize_insurance("Aetna") == "Aetna"

    def test_none_returns_none(self):
        assert _normalize_insurance(None) is None

    def test_empty_string_returns_none(self):
        """Empty string is falsy -> treated as None by the source."""
        assert _normalize_insurance("") is None


# ── _normalize_client_key ─────────────────────────────────────────────────────

class TestNormalizeClientKey:
    def test_uppercase(self):
        assert _normalize_client_key("smith, jane") == "SMITH JANE"

    def test_strips_commas(self):
        assert _normalize_client_key("Smith, Jane") == "SMITH JANE"

    def test_collapses_spaces(self):
        assert _normalize_client_key("Smith,  Jane") == "SMITH JANE"


# ── _dedup_tcn_is_latest ──────────────────────────────────────────────────────

class TestDedupTcnIsLatest:
    def _insert(self, conn, tcn, batch, client, dos, is_latest=True):
        conn.execute(
            "INSERT INTO remittance "
            "(id, batch, payment_date, tcn, client_name_combined, first_dos, "
            " charge_amount, payment_amount, billed_hours, paid_hours, is_latest) "
            "VALUES (nextval('seq_remittance'), ?, '2026-01-15', ?, ?, ?, "
            "        100.0, 90.0, 10.0, 9.0, ?)",
            [batch, tcn, client, dos, is_latest]
        )

    def test_pass1_same_tcn_max_batch_wins(self):
        """Pass 1: same TCN in two batches -> higher batch stays is_latest=True."""
        conn = _db()
        self._insert(conn, "TCN001", 1699, "JONES, BOB", "2026-01-10")
        self._insert(conn, "TCN001", 1877, "JONES, BOB", "2026-01-10")
        _dedup_tcn_is_latest(conn)
        rows = {b: il for b, il in conn.execute(
            "SELECT batch, is_latest FROM remittance WHERE tcn='TCN001' ORDER BY batch"
        ).fetchall()}
        assert rows[1699] is False
        assert rows[1877] is True

    def test_pass2_rebill_different_tcn_max_batch_wins(self):
        """Pass 2: same (client, DOS) with different TCNs (rebill) -> max batch wins."""
        conn = _db()
        self._insert(conn, "TCN_OLD", 1699, "SMITH, ANN", "2026-02-05")
        self._insert(conn, "TCN_NEW", 1877, "SMITH, ANN", "2026-02-05")
        _dedup_tcn_is_latest(conn)
        rows = {tcn: il for tcn, il in conn.execute(
            "SELECT tcn, is_latest FROM remittance "
            "WHERE client_name_combined='SMITH, ANN' ORDER BY tcn"
        ).fetchall()}
        assert rows["TCN_NEW"] is True
        assert rows["TCN_OLD"] is False

    def test_single_record_unchanged(self):
        """A lone record stays is_latest=True after dedup."""
        conn = _db()
        self._insert(conn, "LONE_TCN", 1500, "DAVIS, TOM", "2026-01-20")
        _dedup_tcn_is_latest(conn)
        assert conn.execute(
            "SELECT is_latest FROM remittance WHERE tcn='LONE_TCN'"
        ).fetchone()[0] is True

    def test_dedup_marks_older_batch_not_latest(self):
        """After dedup, the lower-batch row must have is_latest=False."""
        conn = _db()
        self._insert(conn, "TCN_A", 100, "A, B", "2026-01-01")
        self._insert(conn, "TCN_A", 200, "A, B", "2026-01-01")
        _dedup_tcn_is_latest(conn)
        row = conn.execute(
            "SELECT is_latest FROM remittance WHERE tcn='TCN_A' AND batch=100"
        ).fetchone()
        assert row[0] is False


# ── incremental write idempotency ────────────────────────────────────────────

class TestWritePayrollIncremental:
    def _records(self):
        return [{
            "week_start_date": date(2026, 2, 18),
            "week_end_date":   date(2026, 2, 24),
            "paycheck_date":   date(2026, 2, 28),
            "client_name_raw": "JONES, BOB",
            "insurance":       "Medicaid",
            "employee_name":   "Worker, Alice",
            "employee_id":     "1001",
            "regular_hours":   35.0,
            "respite_hours":   0.0,
            "total_hours":     35.0,
            "source_file":     "test.xlsx",
        }]

    def test_idempotent_no_duplicate_rows(self):
        """Same payroll record inserted twice -> only 1 row in DB (ON CONFLICT IGNORE)."""
        conn = _db()
        _write_payroll_incremental(conn, self._records())
        _write_payroll_incremental(conn, self._records())
        count = conn.execute("SELECT COUNT(*) FROM payroll").fetchone()[0]
        assert count == 1, f"Expected 1 row, got {count} — duplicate insert bug"
