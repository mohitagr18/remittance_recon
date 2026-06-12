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
        assert len(summary.unmatched_clients) == 0

    def test_reconciliation_has_expected_columns(self, conn):
        cols = [desc[0] for desc in conn.execute("SELECT * FROM reconciliation LIMIT 0").description]
        assert "result_simple" in cols
        assert "payroll_hours" in cols
        assert "billed_hours" in cols

    def test_summary_as_dict(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        d = summary.as_dict()
        assert isinstance(d, dict)
        assert "payroll_records" in d
        assert "recon_rows" in d
