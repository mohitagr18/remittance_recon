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
        keys = [(r["tcn"], r["payment_date"], r["transaction_type"], r["batch"]) for r in self.records if r["is_latest"]]
        assert len(keys) == len(set(keys))

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
        key = ("TEST, CLIENT", "Unskilled")
        assert key in res
        # Billed hours must be deduplicated to the max daily sum (56.0)
        assert res[key]["billed_hours"] == 56.0
        # Paid hours must be summed cumulatively (10 + 20 + 5 + 21 = 56.0)
        assert res[key]["paid_hours"] == 56.0


class TestDetermineRemittanceCareType:
    """Tests for the rate-based care type classifier."""

    def _make_record(self, billed_hours=None, charge=None, paid_hours=None, pay=None, insurance="Medicaid"):
        from src.etl.remittance import determine_remittance_record_care_type
        r = {
            "billed_hours": billed_hours,
            "charge_amount": charge,
            "paid_hours": paid_hours,
            "payment_amount": pay,
            "insurance": insurance,
        }
        return determine_remittance_record_care_type(r)

    def test_skilled_by_billed_rate(self):
        # ~$54/hr > $30 threshold → Skilled
        assert self._make_record(billed_hours=56.0, charge=3024.0) == "Skilled"

    def test_unskilled_by_billed_rate(self):
        # ~$20/hr < $30 threshold → Unskilled
        assert self._make_record(billed_hours=56.0, charge=1118.0) == "Unskilled"

    def test_skilled_by_paid_rate_fallback(self):
        # No billed_hours, falls back to paid rate ~$54/hr
        assert self._make_record(paid_hours=84.0, pay=4536.0) == "Skilled"

    def test_unskilled_by_paid_rate_fallback(self):
        # No billed_hours, falls back to paid rate ~$20/hr
        assert self._make_record(paid_hours=56.0, pay=1118.0) == "Unskilled"

    def test_skilled_by_insurance_when_no_rate(self):
        # No hours/amounts, falls back to insurance label
        assert self._make_record(insurance="Medicaid & PDN") == "Skilled"

    def test_unskilled_when_no_rate_or_pdn_insurance(self):
        # No hours/amounts, no PDN → Unskilled
        assert self._make_record(insurance="Medicaid") == "Unskilled"

    def test_reversal_skilled_client_has_negative_paid_hours(self):
        # Reversal: negative paid hours with a skilled rate magnitude → Skilled
        # Payer used $54/hr for reversal correctly
        assert self._make_record(billed_hours=-84.0, charge=-4536.0) == "Skilled"

    def test_rate_threshold_boundary(self):
        # Exactly $30.00/hr → Skilled (threshold is >=30)
        assert self._make_record(billed_hours=10.0, charge=300.0) == "Skilled"
        # $29.99/hr → Unskilled
        assert self._make_record(billed_hours=10.0, charge=299.9) == "Unskilled"


class TestCareTypeSplitAggregation:
    """Tests that clients with both Skilled and Unskilled claims produce separate keys."""

    def test_separate_keys_for_same_client_different_care_type(self):
        """A client with both PDN (skilled) and PCA (unskilled) claims → two distinct keys."""
        from datetime import date
        mock_records = [
            {   # Skilled claim (~$54/hr)
                "is_latest": True,
                "client_name_combined": "DREWRY, KAYLA",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 7, 10),
                "billed_hours": 40.0,
                "charge_amount": 2160.0,
                "paid_hours": 40.0,
                "payment_amount": 2160.0,
                "insurance": "Sentara & PDN",
            },
            {   # Unskilled claim (~$20/hr)
                "is_latest": True,
                "client_name_combined": "DREWRY, KAYLA",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 7, 10),
                "billed_hours": 30.0,
                "charge_amount": 600.0,
                "paid_hours": 30.0,
                "payment_amount": 600.0,
                "insurance": "Sentara",
            },
        ]
        res = aggregate_remittance_hours(mock_records)
        skilled_key = ("DREWRY, KAYLA", "Skilled")
        unskilled_key = ("DREWRY, KAYLA", "Unskilled")
        assert skilled_key in res, "Expected a Skilled key for DREWRY, KAYLA"
        assert unskilled_key in res, "Expected an Unskilled key for DREWRY, KAYLA"
        # Verify hours are not double-counted
        assert res[skilled_key]["billed_hours"] == 40.0
        assert res[unskilled_key]["billed_hours"] == 30.0

    def test_all_aggregate_keys_are_tuples(self):
        """Aggregate result keys must be (name, care_type) tuples — not plain strings."""
        from datetime import date
        records = [
            {
                "is_latest": True,
                "client_name_combined": "TEST, CLIENT",
                "first_dos": date(2025, 6, 25),
                "last_dos": date(2025, 7, 1),
                "payment_date": date(2025, 7, 10),
                "billed_hours": 40.0,
                "charge_amount": 2160.0,
                "paid_hours": 40.0,
                "payment_amount": 2160.0,
                "insurance": "Medicaid & PDN",
            }
        ]
        res = aggregate_remittance_hours(records)
        for key in res.keys():
            assert isinstance(key, tuple) and len(key) == 2, \
                f"Expected (name, care_type) tuple, got: {key!r}"
            name, care_type = key
            assert care_type in ("Skilled", "Unskilled"), \
                f"Expected care_type to be 'Skilled' or 'Unskilled', got: {care_type!r}"


