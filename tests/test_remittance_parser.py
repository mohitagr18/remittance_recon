"""tests/test_remittance_parser.py
Tier 2 — live file integration.
Run after dropping a new remittance file in input/master_remit/ and clicking Ingest.
"""
from datetime import date
from src.etl.remittance import (
    parse_remittance, filter_by_dos_range, aggregate_remittance_hours,
)
from src.config import cfg

_TEST_WEEK_START = date(2026, 2, 18)   # UPDATE when verifying a new week
_TEST_WEEK_END   = date(2026, 2, 24)


class TestParseRemittance:
    def setup_method(self):
        self.records = parse_remittance(cfg.remittance_file)

    def test_returns_list(self):
        assert isinstance(self.records, list), (
            "FAIL — parse_remittance() did not return a list.\n"
            f"File: {cfg.remittance_file}\n"
            "CAUSE: The file may be corrupted, password-protected, or saved as .xls.\n"
            "ACTION: Open in Excel, re-save as .xlsx, place in input/master_remit/, re-ingest."
        )

    def test_non_empty(self):
        assert len(self.records) > 0, (
            "FAIL — Remittance file parsed 0 records.\n"
            f"File: {cfg.remittance_file.name}\n"
            "CAUSE — check in this order:\n"
            "  1. Sheet tab is not named exactly 'Remittance Report Template' "
            "(case-sensitive). Common wrong names: 'Sheet1', 'Remittance', 'Report'.\n"
            "  2. Sheet name is correct but rows 4+ are empty (no claim data).\n"
            "ACTION: Open the file, check the sheet tab name. If renamed, restore it to "
            "'Remittance Report Template', re-save, and re-ingest."
        )

    def test_records_have_required_fields(self):
        required = ("tcn", "billed_hours", "paid_hours", "insurance", "first_dos", "last_dos")
        bad = [(i, [f for f in required if f not in r])
               for i, r in enumerate(self.records[:20])
               if not all(f in r for f in required)]
        assert not bad, (
            f"FAIL — {len(bad)} of the first 20 record(s) are missing required fields.\n"
            f"First bad row: index {bad[0][0]}, missing: {bad[0][1]}.\n"
            "CAUSE: Column layout of the remittance sheet has changed. Expected positions:\n"
            "  Col A=Batch, Col B=Payment Date, Col E=Transaction Type,\n"
            "  Col F=Charge, Col G=Payment, Col O=Billed Hrs, Col P=Paid Hrs,\n"
            "  Col R=Client Name (LAST, FIRST), Col S=First DOS, Col T=Last DOS, Col U=TCN.\n"
            "ACTION: Compare the file column headers to the list above. "
            "Flag to developer if columns have been added, removed, or shifted."
        )

    def test_tcn_deduplication(self):
        keys = [(r["tcn"], r["payment_date"], r["transaction_type"], r["batch"])
                for r in self.records if r.get("is_latest")]
        dupes = len(keys) - len(set(keys))
        assert dupes == 0, (
            f"FAIL — {dupes} duplicate TCN+payment_date+transaction_type+batch row(s) found.\n"
            "CAUSE: Two or more rows in the remittance file are identical on all four key "
            "fields — this is a double-entry in the source data.\n"
            "ACTION: Open the remittance file, filter the TCN column (col U) for duplicates. "
            "Flag the duplicates to the billing team to determine which row to remove."
        )

    def test_is_latest_flags(self):
        latest = sum(1 for r in self.records if r.get("is_latest"))
        total  = len(self.records)
        assert latest > 0, (
            "FAIL — No records have is_latest=True after parsing.\n"
            "CAUSE: Deduplication logic treated every record as superseded — reconciliation "
            "would be completely empty.\n"
            "ACTION: Flag to developer — this is an internal deduplication code error."
        )
        assert latest <= total, (
            f"FAIL — is_latest count ({latest}) exceeds total records ({total}).\n"
            "CAUSE: Internal code error in the is_latest flag assignment.\n"
            "ACTION: Flag to developer immediately."
        )


class TestFilterByDosRange:
    def setup_method(self):
        self.all_records = parse_remittance(cfg.remittance_file)

    def test_filters_to_week(self):
        filtered = filter_by_dos_range(self.all_records, _TEST_WEEK_START, _TEST_WEEK_END)
        assert len(filtered) > 0, (
            f"FAIL — No remittance records found for week {_TEST_WEEK_START} to {_TEST_WEEK_END}.\n"
            "NOTE: This is NOT always an error. Remittance commonly lags payroll by "
            "1-3 weeks because payers process claims on their own schedule.\n"
            "CAUSE:\n"
            "  \u2022 Brand-new week just submitted — payer has not processed yet (expected, no action).\n"
            "  \u2022 Old week with no records — worth investigating with billing team.\n"
            "ACTION: Check whether claims for this specific week have been submitted and "
            "whether enough time has passed. If this is a current/recent week, wait for remittance."
        )
        assert len(filtered) < len(self.all_records), (
            "FAIL — Filter returned ALL records unchanged (not a subset).\n"
            "CAUSE: The file may be a single-week extract, not the full cumulative master. "
            "The system expects the FULL master remittance file covering all historical weeks.\n"
            "ACTION: Replace the file with the full cumulative master remittance export and re-ingest."
        )

    def test_all_filtered_records_overlap_week(self):
        filtered = filter_by_dos_range(self.all_records, _TEST_WEEK_START, _TEST_WEEK_END)
        bad = [(r.get("tcn"), str(r.get("first_dos")), str(r.get("last_dos")))
               for r in filtered
               if r.get("first_dos") and r.get("last_dos")
               and not (r["first_dos"] <= _TEST_WEEK_END and r["last_dos"] >= _TEST_WEEK_START)]
        assert not bad, (
            f"FAIL — {len(bad)} record(s) passed the date filter but their DOS do not "
            f"overlap {_TEST_WEEK_START}\u2013{_TEST_WEEK_END}: {bad[:3]}.\n"
            "CAUSE: Internal filter boundary condition error.\n"
            "ACTION: Flag to developer — do not proceed with reconciliation."
        )


class TestAggregateRemittanceHours:
    def setup_method(self):
        all_records = parse_remittance(cfg.remittance_file)
        filtered = filter_by_dos_range(all_records, _TEST_WEEK_START, _TEST_WEEK_END)
        self.aggregated = aggregate_remittance_hours(filtered)

    def test_returns_dict(self):
        assert isinstance(self.aggregated, dict), (
            "FAIL — aggregate_remittance_hours() did not return a dict.\n"
            "CAUSE: Internal code error.  ACTION: Flag to developer immediately."
        )

    def test_non_empty(self):
        assert len(self.aggregated) > 0, (
            f"FAIL — Remittance aggregation produced 0 entries for week "
            f"{_TEST_WEEK_START} to {_TEST_WEEK_END}.\n"
            "ACTION: First check whether test_filters_to_week passed above. "
            "If that also failed, remittance for this week is simply not available yet "
            "(expected for recent weeks). If test_filters_to_week passed, flag to developer."
        )

    def test_values_have_hours(self):
        bad = [(k, v) for k, v in self.aggregated.items()
               if "billed_hours" not in v or not isinstance(v.get("billed_hours"), float)]
        assert not bad, (
            f"FAIL — {len(bad)} aggregated entry/entries are missing numeric billed_hours.\n"
            f"Affected keys: {[k for k, _ in bad[:3]]}.\n"
            "CAUSE: The Billed Hrs column (approx col O) contains non-numeric values "
            "(blank, dash, or text) for some rows.\n"
            "ACTION: Open the remittance file, filter Billed Hrs for non-numeric cells, "
            "fix them, re-save, and re-ingest."
        )

    def test_deduplication_scenario(self):
        """Regression: Scenario 3 multi-payment — billed=max, paid=cumulative."""
        from datetime import date as dt
        mock = [
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025,6,25), "last_dos": dt(2025,7,1),
             "payment_date": dt(2025,7,10),  "billed_hours": 56.0, "paid_hours": 10.0, "insurance": "Medicaid"},
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025,6,25), "last_dos": dt(2025,7,1),
             "payment_date": dt(2025,10,11), "billed_hours": 56.0, "paid_hours": 20.0, "insurance": "Medicaid"},
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025,6,25), "last_dos": dt(2025,7,1),
             "payment_date": dt(2025,10,17), "billed_hours": 26.0, "paid_hours":  5.0, "insurance": "Medicaid"},
            {"is_latest": True, "client_name_combined": "TEST, CLIENT",
             "first_dos": dt(2025,6,25), "last_dos": dt(2025,7,1),
             "payment_date": dt(2025,12,19), "billed_hours": 56.0, "paid_hours": 21.0, "insurance": "Medicaid"},
        ]
        res = aggregate_remittance_hours(mock)
        key = ("TEST, CLIENT", "Unskilled")
        assert key in res, (
            "FAIL — Scenario 3 regression: aggregation key not found after multi-payment dedup.\n"
            "CAUSE: Internal change broke aggregate_remittance_hours().\n"
            "ACTION: Flag to developer — Scenario 3 billing rule has regressed."
        )
        got_b = res[key]["billed_hours"]
        assert got_b == 56.0, (
            f"FAIL — Scenario 3 regression: billed_hours={got_b}, expected 56.0 (max of same-week rows).\n"
            "CAUSE: Billed-hours dedup rule (take max, not sum) has changed.  ACTION: Flag to developer."
        )
        got_p = res[key]["paid_hours"]
        assert got_p == 56.0, (
            f"FAIL — Scenario 3 regression: paid_hours={got_p}, expected 56.0 (10+20+5+21=56).\n"
            "CAUSE: Paid-hours accumulation rule (cumulative sum) has changed.  ACTION: Flag to developer."
        )


class TestDetermineRemittanceCareType:
    """Uses mock data — can only fail after code changes, never due to file changes."""

    def _ct(self, billed_hours=None, charge=None, paid_hours=None, pay=None, insurance="Medicaid"):
        from src.etl.remittance import determine_remittance_record_care_type
        return determine_remittance_record_care_type({
            "billed_hours": billed_hours, "charge_amount": charge,
            "paid_hours": paid_hours, "payment_amount": pay, "insurance": insurance,
        })

    def test_skilled_by_billed_rate(self):
        result = self._ct(billed_hours=56.0, charge=3024.0)
        assert result == "Skilled", (
            f"FAIL — $54/hr billed rate classified as '{result}' instead of 'Skilled'.\n"
            "CAUSE: The $30/hr threshold in determine_remittance_record_care_type() changed.\n"
            "ACTION: Flag to developer — care type classification will be wrong for all high-rate clients."
        )

    def test_unskilled_by_billed_rate(self):
        result = self._ct(billed_hours=56.0, charge=1118.0)
        assert result == "Unskilled", (
            f"FAIL — ~$20/hr billed rate classified as '{result}' instead of 'Unskilled'.\n"
            "ACTION: Flag to developer — rate threshold has changed."
        )

    def test_skilled_by_pdn_insurance(self):
        result = self._ct(insurance="Medicaid & PDN")
        assert result == "Skilled", (
            f"FAIL — Insurance 'Medicaid & PDN' classified as '{result}' instead of 'Skilled'.\n"
            "PDN = Private Duty Nursing = always Skilled.\n"
            "ACTION: Flag to developer — PDN insurance detection has broken. "
            "All PDN clients will be wrongly classified as Unskilled."
        )

    def test_reversal_negative_hours(self):
        result = self._ct(billed_hours=-56.0, charge=-3024.0)
        assert result == "Skilled", (
            f"FAIL — Reversal row (negative hours/charge at Skilled rate) classified as '{result}'.\n"
            "CAUSE: Classifier does not handle negative values (reversals) correctly.\n"
            "ACTION: Flag to developer — reversal rows for Skilled clients will be misclassified."
        )
