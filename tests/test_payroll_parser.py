"""Tests for src/etl/payroll.py — live file integration."""

from pathlib import Path
from src.etl.payroll import parse_payroll, aggregate_payroll_hours
from src.config import cfg


class TestParsePayroll:
    def setup_method(self):
        self.data = parse_payroll(cfg.payroll_file)

    def test_returns_dict(self):
        assert isinstance(self.data, dict), (
            "FAIL — parse_payroll() did not return a dict. "
            "The payroll file may be corrupted or unreadable. "
            "ACTION: Try opening the file in Excel and re-saving it, then re-ingest."
        )

    def test_has_required_keys(self):
        missing = [k for k in ("paycheck_date", "week_start_date", "week_end_date", "records", "employees")
                   if k not in self.data]
        assert not missing, (
            f"FAIL — Payroll parse result is missing keys: {missing}. "
            "The file structure may have changed (e.g. row 1 or row 2 headers moved). "
            "ACTION: Open the payroll file and confirm row 1 starts with 'Paycheck Date:' "
            "and row 2 starts with 'Work Week:'. Flag to developer if layout changed."
        )

    def test_paycheck_date(self):
        got = str(self.data["paycheck_date"])
        assert got != "None", (
            "FAIL — Paycheck date could not be read from the payroll file (returned None). "
            "ACTION: Open the file and check that row 1 cell B1 contains a valid date "
            "next to the label 'Paycheck Date:'. Do not leave it blank or as a formula."
        )

    def test_week_dates(self):
        ws = str(self.data["week_start_date"])
        we = str(self.data["week_end_date"])
        assert ws != "None", (
            "FAIL — Week start date could not be read (returned None). "
            "ACTION: Open the file and check row 2. It should read: "
            "'Work Week: | <start date> | to | | <end date>'. "
            "Dates must be in B2 and E2. Flag to developer if layout changed."
        )
        assert we != "None", (
            "FAIL — Week end date could not be read (returned None). "
            "ACTION: Same as above — check cell E2 of the payroll file."
        )

    def test_records_non_empty(self):
        count = len(self.data["records"])
        assert count > 0, (
            "FAIL — Payroll file parsed 0 detail rows. No employee data was found. "
            f"File: {cfg.payroll_file.name}. "
            "ACTION: Open the file and confirm the MMDDYYYY-named sheet exists "
            "(e.g. '06182026') and has data rows starting at row 4. "
            "If the sheet is named 'Sheet1' or 'Template', rename it to the correct date format."
        )

    def test_records_have_required_fields(self):
        bad = [i for i, r in enumerate(self.data["records"])
               if not all(k in r for k in ("client_name_raw", "insurance", "total_hours", "week_start_date"))]
        assert not bad, (
            f"FAIL — {len(bad)} payroll record(s) are missing required fields "
            f"(first bad row index: {bad[0]}). "
            "This usually means columns shifted in the payroll sheet "
            "(Client=A, Insurance=B, Employee=C, ID=D, Regular hrs=E, Respite hrs=F). "
            "ACTION: Open the file and verify column positions match that order."
        )

    def test_employees_non_empty(self):
        count = len(self.data["employees"])
        assert count > 0, (
            "FAIL — No employee records parsed from the 'Paylocity Mapping' sheet. "
            f"File: {cfg.payroll_file.name}. "
            "ACTION: Check that the payroll file contains a sheet named exactly "
            "'Paylocity Mapping' with employee rows starting at row 3 "
            "(row 1 = blank, row 2 = headers, row 3+ = data). "
            "If the sheet is missing entirely, this is expected — re-export from Paylocity."
        )


class TestAggregatePayrollHours:
    def setup_method(self):
        data = parse_payroll(cfg.payroll_file)
        self.records = data["records"]
        self.aggregated = aggregate_payroll_hours(self.records)

    def test_returns_list(self):
        assert isinstance(self.aggregated, list), (
            "FAIL — aggregate_payroll_hours() did not return a list. "
            "This is an internal code error, not a data issue. "
            "ACTION: Flag to developer immediately. Do not proceed with ingestion."
        )

    def test_all_have_total_hours(self):
        bad = [r for r in self.aggregated
               if "total_hours" not in r or not isinstance(r.get("total_hours"), float)]
        assert not bad, (
            f"FAIL — {len(bad)} aggregated record(s) have missing or non-numeric total_hours. "
            f"First bad record: {bad[0] if bad else 'N/A'}. "
            "ACTION: Check the Regular hrs (col E) and Respite hrs (col F) columns in the "
            "payroll file for non-numeric values like text, dashes, or formulas. "
            "Clear any non-number cells and re-save the file."
        )

    def test_hours_are_positive(self):
        negative = [(r.get("client_name_raw"), r.get("insurance"), r.get("total_hours"))
                    for r in self.aggregated if r.get("total_hours", 0) < 0]
        assert not negative, (
            f"FAIL — {len(negative)} client(s) have negative total hours after aggregation: "
            f"{negative[:5]}. "
            "Negative hours should never appear in payroll. "
            "ACTION: Open the payroll file and search columns E and F for negative values. "
            "Correct the entry and re-ingest the file."
        )

    def test_aggregation_reduces_count(self):
        raw = len(self.records)
        agg = len(self.aggregated)
        assert agg <= raw, (
            f"FAIL — Aggregation produced MORE rows ({agg}) than raw records ({raw}). "
            "This is an internal code error. "
            "ACTION: Flag to developer immediately."
        )
