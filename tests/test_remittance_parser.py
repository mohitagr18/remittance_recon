"""Tests for src/etl/remittance.py"""

from datetime import date
from src.etl.remittance import (
    parse_remittance,
    filter_by_dos_range,
    aggregate_remittance_hours,
)
from src.config import cfg


class TestParseRemittance:
    def setup_method(self):
        self.records = parse_remittance(cfg.remittance_file)

    def test_returns_list(self):
        assert isinstance(self.records, list)

    def test_non_empty(self):
        assert len(self.records) > 0

    def test_records_have_required_fields(self):
        required = ("tcn", "billed_hours", "paid_hours", "insurance", "first_dos", "last_dos")
        for r in self.records[:10]:
            for field in required:
                assert field in r

    def test_tcn_deduplication(self):
        tcns = [r["tcn"] for r in self.records if r["is_latest"]]
        assert len(tcns) == len(set(tcns))

    def test_is_latest_flags(self):
        latest_count = sum(1 for r in self.records if r["is_latest"])
        assert latest_count > 0
        assert latest_count <= len(self.records)


class TestFilterByDosRange:
    def setup_method(self):
        self.all_records = parse_remittance(cfg.remittance_file)

    def test_filters_to_week(self):
        filtered = filter_by_dos_range(self.all_records, date(2026, 2, 18), date(2026, 2, 24))
        assert len(filtered) > 0
        assert len(filtered) < len(self.all_records)

    def test_all_filtered_records_overlap_week(self):
        filtered = filter_by_dos_range(self.all_records, date(2026, 2, 18), date(2026, 2, 24))
        for r in filtered:
            fd = r["first_dos"]
            ld = r["last_dos"]
            if fd and ld:
                assert fd <= date(2026, 2, 24)
                assert ld >= date(2026, 2, 18)


class TestAggregateRemittanceHours:
    def setup_method(self):
        all_records = parse_remittance(cfg.remittance_file)
        filtered = filter_by_dos_range(all_records, date(2026, 2, 18), date(2026, 2, 24))
        self.aggregated = aggregate_remittance_hours(filtered)

    def test_returns_dict(self):
        assert isinstance(self.aggregated, dict)

    def test_non_empty(self):
        assert len(self.aggregated) > 0

    def test_values_have_hours(self):
        for key, data in self.aggregated.items():
            assert "billed_hours" in data
            assert "paid_hours" in data
            assert isinstance(data["billed_hours"], float)

    def test_deduplication_scenario(self):
        # Replicates Scenario 3: Billed 56/10, Billed 56/20, Billed 26/5, Billed 56/21.
        mock_records = [
            {
                "is_latest": True,
                "client_name_combined": "TEST, CLIENT",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 7, 10),
                "billed_hours": 56.0,
                "paid_hours": 10.0,
                "insurance": "Medicaid",
            },
            {
                "is_latest": True,
                "client_name_combined": "TEST, CLIENT",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 10, 11),
                "billed_hours": 56.0,
                "paid_hours": 20.0,
                "insurance": "Medicaid",
            },
            {
                "is_latest": True,
                "client_name_combined": "TEST, CLIENT",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 10, 17),
                "billed_hours": 26.0,
                "paid_hours": 5.0,
                "insurance": "Medicaid",
            },
            {
                "is_latest": True,
                "client_name_combined": "TEST, CLIENT",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 12, 19),
                "billed_hours": 56.0,
                "paid_hours": 21.0,
                "insurance": "Medicaid",
            },
        ]
        res = aggregate_remittance_hours(mock_records)
        assert "TEST, CLIENT" in res
        # Billed hours must be deduplicated to the max daily sum (56.0)
        assert res["TEST, CLIENT"]["billed_hours"] == 56.0
        # Paid hours must be summed cumulatively (10 + 20 + 5 + 21 = 56.0)
        assert res["TEST, CLIENT"]["paid_hours"] == 56.0

