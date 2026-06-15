"""Tests for src/etl/payroll.py"""

from pathlib import Path
from src.etl.payroll import parse_payroll, aggregate_payroll_hours
from src.config import cfg


class TestParsePayroll:
    def setup_method(self):
        self.data = parse_payroll(cfg.payroll_file)

    def test_returns_dict(self):
        assert isinstance(self.data, dict)

    def test_has_required_keys(self):
        for key in ("paycheck_date", "week_start_date", "week_end_date", "records", "employees"):
            assert key in self.data

    def test_paycheck_date(self):
        assert str(self.data["paycheck_date"]) == "2025-07-04"

    def test_week_dates(self):
        assert str(self.data["week_start_date"]) == "2025-06-18"
        assert str(self.data["week_end_date"]) == "2025-06-24"

    def test_records_non_empty(self):
        assert len(self.data["records"]) > 0

    def test_records_have_required_fields(self):
        for r in self.data["records"]:
            assert "client_name_raw" in r
            assert "insurance" in r
            assert "total_hours" in r
            assert "week_start_date" in r

    def test_employees_non_empty(self):
        assert len(self.data["employees"]) > 0


class TestAggregatePayrollHours:
    def setup_method(self):
        data = parse_payroll(cfg.payroll_file)
        self.aggregated = aggregate_payroll_hours(data["records"])

    def test_returns_list(self):
        assert isinstance(self.aggregated, list)

    def test_all_have_total_hours(self):
        for r in self.aggregated:
            assert "total_hours" in r
            assert isinstance(r["total_hours"], float)

    def test_hours_are_positive(self):
        for r in self.aggregated:
            assert r["total_hours"] >= 0

    def test_aggregation_reduces_count(self):
        data = parse_payroll(cfg.payroll_file)
        assert len(self.aggregated) <= len(data["records"])
