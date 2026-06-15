"""Tests for src/etl/pipeline.py — integration test"""

from src.etl.pipeline import PipelineSummary
from src.db.connection import get_conn


class TestPipeline:
    def test_summary_populated(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        assert summary.payroll_records > 0
        assert summary.payroll_clients > 0
        assert summary.remittance_records > 0
        assert summary.recon_rows > 0

    def test_all_tables_written(self, db_path):
        with get_conn(db_path, read_only=True) as conn:
            for table in ("name_match", "copay_clients", "employees", "payroll", "remittance", "reconciliation"):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count > 0, f"Table {table} is empty"

    def test_reconciliation_results(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        assert summary.result_good + summary.result_followup + summary.result_no_payroll == summary.recon_rows

    def test_no_unmatched_clients(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        # Known data-quality issues in payroll source files that cannot be resolved
        # in code — they require fixes to the source data or name_match Excel:
        #   - 'ADAM, ALEXANDRU LPN': payroll uses FIRST,LAST order; name_match has LAST,FIRST
        #   - 'WILLAIMS-JONES, LANIECE': typo in payroll (WILLAIMS vs WILLIAMS)
        KNOWN_DATA_QUALITY_EXCEPTIONS = {
            "ADAM, ALEXANDRU LPN",
            "WILLAIMS-JONES, LANIECE",
        }
        unexpected = [c for c in summary.unmatched_clients if c not in KNOWN_DATA_QUALITY_EXCEPTIONS]
        assert len(unexpected) == 0, f"Unexpected unmatched clients: {unexpected}"

    def test_reconciliation_has_expected_columns(self, conn):
        cols = [desc[0] for desc in conn.execute("SELECT * FROM reconciliation LIMIT 0").description]
        assert "result_simple" in cols
        assert "payroll_hours" in cols
        assert "billed_hours" in cols
        assert "care_type" in cols

    def test_care_type_values_valid(self, conn):
        """All care_type values should be 'Skilled' or 'Unskilled'."""
        rows = conn.execute(
            "SELECT DISTINCT care_type FROM reconciliation WHERE care_type IS NOT NULL"
        ).fetchall()
        valid = {"Skilled", "Unskilled"}
        for (ct,) in rows:
            assert ct in valid, f"Unexpected care_type value: {ct!r}"

    def test_no_runaway_negative_paid_hours(self, conn):
        """
        After reversal rate correction, no client should have paid hours < -200.
        Before the fix, Soleil Pegram showed -205.15 due to payer using unskilled
        rate to divide a skilled dollar reversal. This acts as a regression guard.
        """
        rows = conn.execute(
            """SELECT client_name_payroll, week_start_date, paid_hours
               FROM reconciliation
               WHERE paid_hours < -200"""
        ).fetchall()
        assert len(rows) == 0, (
            f"Found {len(rows)} reconciliation rows with paid_hours < -200 "
            f"(reversal rate correction may have regressed): {rows[:5]}"
        )

    def test_summary_as_dict(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        d = summary.as_dict()
        assert isinstance(d, dict)
        assert "payroll_records" in d
        assert "recon_rows" in d

    def test_no_silent_not_billed_when_remittance_exists(self, conn):
        """
        Regression guard for care-type mismatch silent failure (e.g. ROBINSON, GEORGE LPN):
        if a client has MATCHED status (remittance name is known) AND remittance records exist
        for that week, billed_hours must not be 0 (which would falsely show as Not Billed).
        Previously this was silently failing because the (name, care_type) join key mismatched
        when payroll suffix implied Skilled but insurance billed at unskilled rates.
        """
        # Find clients with MATCHED status but 0 billed hours AND 0 paid hours
        # who also have remittance records for that week — that's the broken scenario
        rows = conn.execute("""
            SELECT r.client_name_payroll, r.week_start_date, r.billed_hours, r.paid_hours,
                   r.match_status, r.result_detailed
            FROM reconciliation r
            WHERE r.match_status = 'MATCHED'
              AND r.payroll_hours > 0
              AND r.billed_hours = 0
              AND r.paid_hours = 0
              AND r.result_detailed = 'Not Billed'
              -- Only flag if remittance record exists for this client in the same week
              AND EXISTS (
                  SELECT 1 FROM remittance rem
                  WHERE rem.client_name_combined = r.client_name_remittance
                    AND rem.is_latest = true
                    AND rem.first_dos <= r.week_end_date
                    AND rem.last_dos >= r.week_start_date
              )
        """).fetchall()
        assert len(rows) == 0, (
            f"Found {len(rows)} MATCHED clients showing Not Billed despite having remittance records "
            f"(care-type mismatch fallback may have regressed): {[r[0] for r in rows[:5]]}"
        )
