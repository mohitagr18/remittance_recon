"""tests/test_payroll_parser.py
Tier 2 — live file integration.
Run after dropping a new payroll file in input/payroll/ and clicking Ingest.

Every assertion includes:
  FAIL   — what broke
  CAUSE  — most likely reasons
  ACTION — exact steps the operator takes next
"""
from src.etl.payroll import parse_payroll, aggregate_payroll_hours
from src.config import cfg


class TestParsePayroll:
    def setup_method(self):
        self.data = parse_payroll(cfg.payroll_file)

    def test_returns_dict(self):
        assert isinstance(self.data, dict), (
            "FAIL — parse_payroll() did not return a dict.\n"
            f"File: {cfg.payroll_file}\n"
            "CAUSE: The file may be corrupted, password-protected, or saved as .xls "
            "instead of .xlsx.\n"
            "ACTION: Open the file in Excel and re-save it as .xlsx, "
            "then re-ingest from Data Management."
        )

    def test_has_required_keys(self):
        required = ("paycheck_date", "week_start_date", "week_end_date", "records", "employees")
        missing = [k for k in required if k not in self.data]
        assert not missing, (
            f"FAIL — Payroll parse result is missing keys: {missing}.\n"
            "CAUSE: The file structure has changed. The parser expects:\n"
            "  Row 1: A1='Paycheck Date:', B1=actual date\n"
            "  Row 2: A2='Work Week:', B2=start date, E2=end date\n"
            "  A sheet tab named in MMDDYYYY format (e.g. '06182026')\n"
            "  A sheet tab named exactly 'Paylocity Mapping'\n"
            "ACTION: Open the file and verify rows 1-2 and both sheet names match. "
            "Flag to developer if the Paylocity export format has changed."
        )

    def test_paycheck_date(self):
        got = self.data.get("paycheck_date")
        assert got is not None and str(got) != "None", (
            "FAIL — Paycheck date could not be read from the file (returned None).\n"
            f"File: {cfg.payroll_file.name}\n"
            "CAUSE: Cell B1 is blank, contains plain text, or is a formula returning empty.\n"
            "ACTION: Open the file and confirm B1 contains a valid Excel date "
            "(e.g. 07/04/2025). If it shows as text, re-format that cell as a Date type."
        )

    def test_week_dates(self):
        ws = self.data.get("week_start_date")
        we = self.data.get("week_end_date")
        assert ws is not None and str(ws) != "None", (
            "FAIL — Week start date could not be read (returned None).\n"
            f"File: {cfg.payroll_file.name}\n"
            "CAUSE: Cell B2 is blank or contains text. "
            "Row 2 must be: A2='Work Week:' | B2=<start date> | D2='to' | E2=<end date>.\n"
            "ACTION: Open the file and confirm B2 contains a valid date formatted as Date."
        )
        assert we is not None and str(we) != "None", (
            "FAIL — Week end date could not be read (returned None).\n"
            f"File: {cfg.payroll_file.name}\n"
            "CAUSE: Cell E2 is blank or contains text.\n"
            "ACTION: Open the file and confirm E2 contains a valid date formatted as Date."
        )

    def test_records_non_empty(self):
        count = len(self.data.get("records", []))
        assert count > 0, (
            "FAIL — Payroll file parsed 0 detail rows. No employee records were found.\n"
            f"File: {cfg.payroll_file.name}\n"
            "CAUSE — check in this order:\n"
            "  1. The date-named sheet does not exist. It must be named like '06182026' "
            "(MMDDYYYY), not 'Sheet1', 'Data', or 'Template'.\n"
            "  2. The sheet exists but has no data rows (nothing below row 3).\n"
            "  3. A blank template was accidentally placed in input/payroll/.\n"
            "ACTION: Open the file, find the MMDDYYYY-named sheet, confirm data starts "
            "at row 4. If the sheet is misnamed, rename it to the correct date format, "
            "re-save, and re-ingest."
        )

    def test_records_have_required_fields(self):
        required = ("client_name_raw", "insurance", "total_hours", "week_start_date")
        bad = [(i, [f for f in required if f not in r])
               for i, r in enumerate(self.data.get("records", []))
               if not all(f in r for f in required)]
        assert not bad, (
            f"FAIL — {len(bad)} payroll row(s) are missing required fields.\n"
            f"First bad row: index {bad[0][0]}, missing: {bad[0][1]}.\n"
            "CAUSE: Columns have shifted in the payroll sheet. "
            "Expected order: A=Client Name, B=Insurance, C=Employee Name, "
            "D=Employee ID, E=Regular Hrs, F=Respite Hrs.\n"
            "ACTION: Open the sheet and verify columns A-F match this order exactly. "
            "If a column was inserted or moved, flag to developer."
        )

    def test_employees_non_empty(self):
        count = len(self.data.get("employees", []))
        assert count > 0, (
            "FAIL — No employee records found (Paylocity Mapping sheet empty or missing).\n"
            f"File: {cfg.payroll_file.name}\n"
            "CAUSE: The 'Paylocity Mapping' sheet is absent or has no data rows.\n"
            "  Sheet must be named exactly: Paylocity Mapping (case-sensitive)\n"
            "  Row 1=blank, Row 2=headers, Row 3+=employee data\n"
            "ACTION: Check the sheet tab. If missing, re-export the payroll file from "
            "Paylocity. Note: this only affects employee reporting — reconciliation "
            "will still run without it."
        )


class TestAggregatePayrollHours:
    def setup_method(self):
        data = parse_payroll(cfg.payroll_file)
        self.records = data.get("records", [])
        self.aggregated = aggregate_payroll_hours(self.records)

    def test_returns_list(self):
        assert isinstance(self.aggregated, list), (
            "FAIL — aggregate_payroll_hours() did not return a list.\n"
            "CAUSE: This is an internal code error, not a data file issue.\n"
            "ACTION: Flag to developer immediately. Do not proceed with ingestion."
        )

    def test_all_have_total_hours(self):
        bad = [r for r in self.aggregated
               if "total_hours" not in r or not isinstance(r.get("total_hours"), float)]
        assert not bad, (
            f"FAIL — {len(bad)} aggregated record(s) have missing or non-numeric total_hours.\n"
            f"Example bad record: {bad[0] if bad else 'N/A'}.\n"
            "CAUSE: Regular Hrs (col E) or Respite Hrs (col F) contains non-numeric "
            "values such as dashes, text, or blanks for some rows.\n"
            "ACTION: Open the payroll sheet, filter columns E and F for non-numeric "
            "values, replace any blank or text cells with 0, re-save, and re-ingest."
        )

    def test_hours_are_positive(self):
        negative = [(r.get("client_name_raw"), r.get("insurance"), r.get("total_hours"))
                    for r in self.aggregated if r.get("total_hours", 0) < 0]
        assert not negative, (
            f"FAIL — {len(negative)} client(s) have negative total hours: {negative[:5]}.\n"
            "CAUSE: Negative values exist in Regular Hrs (col E) or Respite Hrs (col F). "
            "This should never occur in payroll data.\n"
            "ACTION: Open the payroll file, search columns E and F for negative numbers, "
            "correct them, re-save, and re-ingest."
        )

    def test_aggregation_reduces_count(self):
        raw, agg = len(self.records), len(self.aggregated)
        assert agg <= raw, (
            f"FAIL — Aggregation expanded rows from {raw} to {agg} (should reduce or stay equal).\n"
            "CAUSE: Internal code error in aggregate_payroll_hours().\n"
            "ACTION: Flag to developer immediately."
        )
