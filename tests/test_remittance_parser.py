"""Tests for src/etl/remittance.py — live file integration."""

from datetime import date
from src.etl.remittance import (
    parse_remittance,
    filter_by_dos_range,
    aggregate_remittance_hours,
)
from src.config import cfg

# The week used for filter tests — matches the most recently verified payroll week.
# Update this constant when verifying a new file against a new week.
_TEST_WEEK_START = date(2026, 2, 18)
_TEST_WEEK_END   = date(2026, 2, 24)


class TestParseRemittance:
    def setup_method(self):
        self.records = parse_remittance(cfg.remittance_file)

    def test_returns_list(self):
        assert isinstance(self.records, list), (
            "FAIL — parse_remittance() did not return a list. "
            "The remittance file may be corrupted or in an unexpected format. "
            "ACTION: Try opening the file in Excel and re-saving it as .xlsx, "
            "then place it back in input/master_remit/ and re-ingest."
        )

    def test_non_empty(self):
        assert len(self.records) > 0, (
            "FAIL — Remittance file parsed 0 records. "
            f"File: {cfg.remittance_file.name}. "
            "The most common cause is the sheet name. The parser requires a sheet "
            "named exactly: 'Remittance Report Template'. "
            "ACTION: Open the file and check the sheet tab name. "
            "If it has been renamed (e.g. 'Sheet1', 'Remittance', 'Report'), "
            "rename it back to 'Remittance Report Template' and re-save. "
            "If the sheet name is correct but the file is empty, check that "
            "row 4 onward contains claim data (rows 1-3 are metadata/headers)."
        )

    def test_records_have_required_fields(self):
        required = ("tcn", "billed_hours", "paid_hours", "insurance", "first_dos", "last_dos")
        bad = []
        for i, r in enumerate(self.records[:10]):
            missing = [f for f in required if f not in r]
            if missing:
                bad.append((i, missing))
        assert not bad, (
            f"FAIL — {len(bad)} of the first 10 remittance record(s) are missing required fields: "
            f"{bad}. "
            "This means the remittance file column layout has changed. "
            "The parser expects columns in this order: Batch, Date, Transaction, "
            "Match Status, Claim, Transaction Type, Charge, Payment, Allowed, "
            "First Name, Last Name, First DOS, Last DOS, TCN, Billed Hrs, Paid Hrs... "
            "ACTION: Compare the file's column headers to this expected layout. "
            "Flag to developer if the column order has changed."
        )

    def test_tcn_deduplication(self):
        keys = [(r["tcn"], r["payment_date"], r["transaction_type"], r["batch"])
                for r in self.records if r["is_latest"]]
        dupes = len(keys) - len(set(keys))
        assert dupes == 0, (
            f"FAIL — {dupes} duplicate TCN+date+type+batch combination(s) found in the "
            "remittance file after deduplication. "
            "This means two rows in the file are completely identical on all four key fields. "
            "ACTION: Open the remittance file and filter for duplicate TCN values. "
            "This is likely a double-entry or copy-paste error in the source data. "
            "Flag to the billing team to remove the duplicate row."
        )

    def test_is_latest_flags(self):
        latest_count = sum(1 for r in self.records if r["is_latest"])
        total = len(self.records)
        assert latest_count > 0, (
            "FAIL — No records have is_latest=True after parsing. "
            "This means the deduplication logic treated all records as superseded, "
            "which would result in a completely empty reconciliation. "
            "ACTION: Flag to developer — this is an internal code error."
        )
        assert latest_count <= total, (
            f"FAIL — is_latest count ({latest_count}) exceeds total records ({total}). "
            "This is an internal code error. "
            "ACTION: Flag to developer immediately."
        )


class TestFilterByDosRange:
    def setup_method(self):
        self.all_records = parse_remittance(cfg.remittance_file)

    def test_filters_to_week(self):
        filtered = filter_by_dos_range(self.all_records, _TEST_WEEK_START, _TEST_WEEK_END)
        assert len(filtered) > 0, (
            f"FAIL — No remittance records found for the week "
            f"{_TEST_WEEK_START} to {_TEST_WEEK_END}. "
            "This means the remittance file does not yet contain claims "
            "with dates of service in that week. "
            "NOTE: This is NOT always an error. Remittance often lags payroll by "
            "1-3 weeks — payers process and post payments on their own schedule. "
            "ACTION: Check whether claims for that week have been submitted and "
            "enough time has passed for the payer to process them. "
            "If this is a newly ingested file and the week is current, "
            "remittance data may simply not be available yet — this is expected."
        )
        assert len(filtered) < len(self.all_records), (
            "FAIL — Filter returned ALL records (not a subset). "
            "The date filter did not reduce the record count, which means "
            "all records in the file happen to fall within that one week — "
            "this is unexpected for a cumulative remittance file. "
            "ACTION: Check whether this file is the full master remittance "
            "or only a single-week extract. The system expects the full master file."
        )

    def test_all_filtered_records_overlap_week(self):
        filtered = filter_by_dos_range(self.all_records, _TEST_WEEK_START, _TEST_WEEK_END)
        bad = [(r.get("tcn"), r.get("first_dos"), r.get("last_dos"))
               for r in filtered
               if r.get("first_dos") and r.get("last_dos")
               and not (r["first_dos"] <= _TEST_WEEK_END and r["last_dos"] >= _TEST_WEEK_START)]
        assert not bad, (
            f"FAIL — {len(bad)} remittance record(s) passed the date filter but their "
            f"dates of service do not actually overlap the week "
            f"{_TEST_WEEK_START} to {_TEST_WEEK_END}: {bad[:3]}. "
            "This is an internal filter logic error. "
            "ACTION: Flag to developer — do not proceed with reconciliation."
        )


class TestAggregateRemittanceHours:
    def setup_method(self):
        all_records = parse_remittance(cfg.remittance_file)
        filtered = filter_by_dos_range(all_records, _TEST_WEEK_START, _TEST_WEEK_END)
        self.aggregated = aggregate_remittance_hours(filtered)
        self._week_str = f"{_TEST_WEEK_START} to {_TEST_WEEK_END}"

    def test_returns_dict(self):
        assert isinstance(self.aggregated, dict), (
            "FAIL — aggregate_remittance_hours() did not return a dict. "
            "This is an internal code error. "
            "ACTION: Flag to developer immediately."
        )

    def test_non_empty(self):
        assert len(self.aggregated) > 0, (
            f"FAIL — Remittance aggregation produced 0 entries for week {self._week_str}. "
            "This means no claimable records survived filtering and aggregation. "
            "ACTION: First check whether test_filters_to_week passed. "
            "If that also failed, the remittance file does not yet cover this week — expected. "
            "If test_filters_to_week passed but this fails, flag to developer."
        )

    def test_values_have_hours(self):
        bad = [(k, v) for k, v in self.aggregated.items()
               if "billed_hours" not in v or not isinstance(v.get("billed_hours"), float)]
        assert not bad, (
            f"FAIL — {len(bad)} aggregated remittance entries are missing numeric billed_hours: "
            f"{[k for k, _ in bad[:3]]}. "
            "This usually means the Billed Hrs column (col O in the remittance sheet) "
            "contains non-numeric values for some rows. "
            "ACTION: Open the remittance file, filter the Billed Hrs column for blanks "
            "or text values, and fix those cells."
        )

    def test_deduplication_scenario(self):
        """Regression: Scenario 3 multi-payment dedup — billed max, paid cumulative."""
        from datetime import date as dt
        mock_records = [
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025, 6, 25), "last_dos": dt(2025, 7, 1),
             "payment_date": dt(2025, 7, 10),  "billed_hours": 56.0, "paid_hours": 10.0, "insurance": "Medicaid"},
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025, 6, 25), "last_dos": dt(2025, 7, 1),
             "payment_date": dt(2025, 10, 11), "billed_hours": 56.0, "paid_hours": 20.0, "insurance": "Medicaid"},
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025, 6, 25), "last_dos": dt(2025, 7, 1),
             "payment_date": dt(2025, 10, 17), "billed_hours": 26.0, "paid_hours":  5.0, "insurance": "Medicaid"},
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025, 6, 25), "last_dos": dt(2025, 7, 1),
             "payment_date": dt(2025, 12, 19), "billed_hours": 56.0, "paid_hours": 21.0, "insurance": "Medicaid"},
        ]
        res = aggregate_remittance_hours(mock_records)
        key = ("TEST, CLIENT", "Unskilled")
        assert key in res, (
            "FAIL — Multi-payment deduplication regression: aggregation key not found. "
            "This is an internal code error (business rule regression). "
            "ACTION: Flag to developer — the deduplication logic in aggregate_remittance_hours() "
            "has likely been changed and the Scenario 3 rule is broken."
        )
        got_billed = res[key]["billed_hours"]
        assert got_billed == 56.0, (
            f"FAIL — Billed hours deduplication regression: expected 56.0 (max daily sum), "
            f"got {got_billed}. "
            "The rule is: billed hours = max billed amount for the same date range "
            "(same service week should not be double-counted). "
            "ACTION: Flag to developer — Scenario 3 business rule has regressed."
        )
        got_paid = res[key]["paid_hours"]
        assert got_paid == 56.0, (
            f"FAIL — Paid hours accumulation regression: expected 56.0 (10+20+5+21), "
            f"got {got_paid}. "
            "The rule is: paid hours = cumulative sum across all payment dates for the same week. "
            "ACTION: Flag to developer — Scenario 3 business rule has regressed."
        )


class TestDetermineRemittanceCareType:
    """Tests for the rate-based Skilled/Unskilled classifier — all use mock data."""

    def _make(self, billed_hours=None, charge=None, paid_hours=None, pay=None, insurance="Medicaid"):
        from src.etl.remittance import determine_remittance_record_care_type
        return determine_remittance_record_care_type({
            "billed_hours": billed_hours, "charge_amount": charge,
            "paid_hours": paid_hours, "payment_amount": pay, "insurance": insurance,
        })

    def test_skilled_by_billed_rate(self):
        result = self._make(billed_hours=56.0, charge=3024.0)
        assert result == "Skilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Skilled' "
            "for a $54/hr billed rate (above the $30/hr threshold). "
            "ACTION: Flag to developer — the care type rate threshold may have changed."
        )

    def test_unskilled_by_billed_rate(self):
        result = self._make(billed_hours=56.0, charge=1118.0)
        assert result == "Unskilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Unskilled' "
            "for a ~$20/hr billed rate (below the $30/hr threshold). "
            "ACTION: Flag to developer — the care type rate threshold may have changed."
        )

    def test_skilled_by_paid_rate_fallback(self):
        result = self._make(paid_hours=84.0, pay=4536.0)
        assert result == "Skilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Skilled' "
            "when using paid rate fallback (~$54/hr, no billed hours provided). "
            "ACTION: Flag to developer."
        )

    def test_unskilled_by_paid_rate_fallback(self):
        result = self._make(paid_hours=56.0, pay=1118.0)
        assert result == "Unskilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Unskilled' "
            "when using paid rate fallback (~$20/hr). "
            "ACTION: Flag to developer."
        )

    def test_skilled_by_insurance_when_no_rate(self):
        result = self._make(insurance="Medicaid & PDN")
        assert result == "Skilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Skilled' "
            "for 'Medicaid & PDN' insurance (PDN = Private Duty Nursing = Skilled). "
            "ACTION: Flag to developer — PDN insurance label detection has broken."
        )

    def test_unskilled_when_no_rate_or_pdn_insurance(self):
        result = self._make(insurance="Medicaid")
        assert result == "Unskilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Unskilled' "
            "when no rate data is present and insurance has no PDN indicator. "
            "ACTION: Flag to developer."
        )

    def test_reversal_skilled_client_has_negative_paid_hours(self):
        result = self._make(billed_hours=-84.0, charge=-4536.0)
        assert result == "Skilled", (
            f"FAIL — Rate classifier returned '{result}' instead of 'Skilled' "
            "for a negative (reversal) skilled rate. "
            "The reversal used the correct Skilled rate magnitude (~$54/hr) "
            "but the classifier did not handle negative values correctly. "
            "ACTION: Flag to developer — the reversal rate correction has regressed."
        )

    def test_rate_threshold_boundary(self):
        at_threshold = self._make(billed_hours=10.0, charge=300.0)
        assert at_threshold == "Skilled", (
            f"FAIL — Exactly $30.00/hr should classify as Skilled (threshold is >=30), "
            f"got '{at_threshold}'. "
            "ACTION: Flag to developer — threshold boundary condition has changed."
        )
        just_under = self._make(billed_hours=10.0, charge=299.9)
        assert just_under == "Unskilled", (
            f"FAIL — $29.99/hr should classify as Unskilled (below $30 threshold), "
            f"got '{just_under}'. "
            "ACTION: Flag to developer — threshold boundary condition has changed."
        )


class TestCareTypeSplitAggregation:
    def test_separate_keys_for_same_client_different_care_type(self):
        """A client with PDN (skilled) and PCA (unskilled) claims must produce two keys."""
        from datetime import date as dt
        mock_records = [
            {"is_latest": True, "client_name_combined": "DREWRY, KAYLA",
             "first_dos": dt(2025, 6, 25), "last_dos": dt(2025, 7, 1),
             "payment_date": dt(2025, 7, 10),
             "billed_hours": 40.0, "charge_amount": 2160.0,
             "paid_hours": 40.0, "payment_amount": 2160.0, "insurance": "Sentara & PDN"},
            {"is_latest": True, "client_name_combined": "DREWRY, KAYLA",
             "first_dos": dt(2025, 6, 25), "last_dos": dt(2025, 7, 1),
             "payment_date": dt(2025, 7, 10),
             "billed_hours": 84.0, "charge_amount": 1680.0,
             "paid_hours": 84.0, "payment_amount": 1680.0, "insurance": "Sentara"},
        ]
        res = aggregate_remittance_hours(mock_records)
        skilled_key   = ("DREWRY, KAYLA", "Skilled")
        unskilled_key = ("DREWRY, KAYLA", "Unskilled")
        assert skilled_key in res and unskilled_key in res, (
            f"FAIL — Dual care-type client 'DREWRY, KAYLA' did not produce separate "
            f"Skilled and Unskilled aggregation keys. Got keys: {list(res.keys())}. "
            "This regression would silently merge hours for clients with both PDN and PCA "
            "claims, producing wrong reconciliation totals. "
            "ACTION: Flag to developer immediately — this is a P0 regression."
        )
