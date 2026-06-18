"""
tests/test_pipeline.py
Full integration tests using real Excel files.

Every assertion includes a plain-English failure message that tells the operator
exactly what went wrong and what to do next. No developer needed to interpret output.
"""

from src.etl.pipeline import PipelineSummary
from src.db.connection import get_conn


class TestPipeline:
    def test_summary_populated(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        assert summary.payroll_records > 0, (
            "FAIL — Pipeline ran but wrote 0 payroll records to the database. "
            "This means the payroll file was found but no detail rows could be parsed. "
            "ACTION: Go to Data Management → File Ingestion and confirm the payroll file "
            "shows status 🆕 New. Then open the payroll Excel and verify the MMDDYYYY-named "
            "sheet (e.g. '06182026') exists and contains data rows from row 4 downward. "
            "If the sheet is named 'Sheet1' or 'Template', rename it and re-ingest."
        )
        assert summary.payroll_clients > 0, (
            "FAIL — Pipeline ran but found 0 distinct payroll clients. "
            "Payroll records were written but every row is missing a client name (col A is blank). "
            "ACTION: Open the payroll file and check column A from row 4 onward. "
            "Every detail row must have a client name. Fix blank cells and re-ingest."
        )
        assert summary.remittance_records > 0, (
            "FAIL — Pipeline ran but wrote 0 remittance records to the database. "
            "The remittance file was found but no claim rows could be parsed. "
            "ACTION: Open the remittance Excel and verify: "
            "(1) the sheet tab is named exactly 'Remittance Report Template', "
            "(2) data rows start at row 4 (rows 1-3 are metadata/headers), "
            "(3) the file is the full master remittance, not a single-week export."
        )
        assert summary.recon_rows > 0, (
            "FAIL — Pipeline ran but produced 0 reconciliation rows. "
            "Both payroll and remittance records were ingested but could not be joined. "
            "The most likely cause is that no payroll client names matched any remittance "
            "client names through the Name Match mapping. "
            "ACTION: Go to Admin → Name Match Manager. Check that the 'Name Match' sheet "
            "in your Weekly Recon Excel file contains mappings for the current payroll clients. "
            "If new client names appear in payroll this week, add them to the Name Match sheet, "
            "save the file, then click 🔁 Rebuild Reconciliation in Data Management."
        )

    def test_all_tables_written(self, db_path):
        with get_conn(db_path, read_only=True) as conn:
            for table in ("name_match", "copay_clients", "employees",
                          "payroll", "remittance", "reconciliation"):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                table_tips = {
                    "name_match": (
                        "The Name Match sheet in your Weekly Recon Excel file is missing or empty. "
                        "ACTION: Open the Weekly Recon file and confirm the 'Name Match' sheet "
                        "exists with at least one mapping row."
                    ),
                    "copay_clients": (
                        "The Copay sheet in your Weekly Recon Excel file is missing or empty. "
                        "ACTION: Open the Weekly Recon file and confirm the 'Copay' sheet exists. "
                        "If no clients have copay, this is expected — this test can be ignored."
                    ),
                    "employees": (
                        "The 'Paylocity Mapping' sheet in the payroll file is missing or has no data rows. "
                        "ACTION: Open the payroll file. The 'Paylocity Mapping' sheet must exist with "
                        "employee rows starting at row 3 (row 1 = blank, row 2 = headers, row 3+ = data). "
                        "Re-export from Paylocity if this sheet is absent."
                    ),
                    "payroll": (
                        "No payroll records were written. See test_summary_populated for details."
                    ),
                    "remittance": (
                        "No remittance records were written. See test_summary_populated for details."
                    ),
                    "reconciliation": (
                        "Reconciliation table is empty. See test_summary_populated for details."
                    ),
                }
                assert count > 0, (
                    f"FAIL — Database table '{table}' is empty after pipeline run. "
                    + table_tips.get(table, "ACTION: Flag to developer.")
                )

    def test_reconciliation_results(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        total = summary.result_good + summary.result_followup + summary.result_no_payroll
        assert total == summary.recon_rows, (
            f"FAIL — Reconciliation result counts don't add up. "
            f"Good={summary.result_good} + Follow-up={summary.result_followup} + "
            f"No Payroll={summary.result_no_payroll} = {total}, "
            f"but total recon rows = {summary.recon_rows}. "
            "This means some rows have a NULL or unrecognised result_simple value. "
            "ACTION: Flag to developer — this is an internal classification bug, not a data issue."
        )

    def test_no_unmatched_clients(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        # Known data-quality issues that cannot be resolved in code
        KNOWN_EXCEPTIONS = {
            "ADAM, ALEXANDRU LPN",      # payroll uses FIRST,LAST order; name_match has LAST,FIRST
            "WILLAIMS-JONES, LANIECE",  # typo in payroll (WILLAIMS vs WILLIAMS)
        }
        unexpected = [c for c in summary.unmatched_clients if c not in KNOWN_EXCEPTIONS]
        assert len(unexpected) == 0, (
            f"FAIL — {len(unexpected)} payroll client(s) could not be matched to any "
            f"remittance record because they are missing from the Name Match mapping: "
            f"{unexpected}. "
            "These clients will show as 'No Payroll Hours' in the dashboard and "
            "their remittance data will not be reconciled. "
            "ACTION: Go to Admin → Name Match Manager. For each name listed above, "
            "find the matching name in the remittance file and add the mapping. "
            "Then click 🔁 Rebuild Reconciliation in Data Management. "
            "If the name is genuinely new this week (e.g. a new client), "
            "check with the billing team whether remittance has been submitted for them yet."
        )

    def test_reconciliation_has_expected_columns(self, conn):
        cols = [desc[0] for desc in conn.execute(
            "SELECT * FROM reconciliation LIMIT 0").description]
        required = ("result_simple", "payroll_hours", "billed_hours",
                    "paid_hours", "care_type", "match_status")
        missing = [c for c in required if c not in cols]
        assert not missing, (
            f"FAIL — Reconciliation table is missing expected columns: {missing}. "
            "This means the database schema has changed and the reconciliation table "
            "does not match what the application expects. "
            "ACTION: Flag to developer immediately. Do not proceed with data review "
            "until the schema migration is confirmed complete."
        )

    def test_care_type_values_valid(self, conn):
        rows = conn.execute(
            "SELECT DISTINCT care_type FROM reconciliation WHERE care_type IS NOT NULL"
        ).fetchall()
        invalid = [ct for (ct,) in rows if ct not in {"Skilled", "Unskilled"}]
        assert not invalid, (
            f"FAIL — Unexpected care_type value(s) found in reconciliation: {invalid}. "
            "Valid values are only 'Skilled' or 'Unskilled'. "
            "This means the care type classifier produced an unexpected result "
            "for some client+insurance combination. "
            "ACTION: Flag to developer with the client names that have these "
            "invalid care_type values so the classifier logic can be corrected."
        )

    def test_no_runaway_negative_paid_hours(self, conn):
        rows = conn.execute(
            """SELECT client_name_payroll, week_start_date, paid_hours
               FROM reconciliation
               WHERE paid_hours < -200"""
        ).fetchall()
        assert len(rows) == 0, (
            f"FAIL — {len(rows)} reconciliation row(s) have paid_hours below -200, "
            f"which indicates a reversal rate correction bug: "
            f"{[(r[0], str(r[1]), r[2]) for r in rows[:5]]}. "
            "A payer reversal used a different hourly rate than the original payment, "
            "causing the hour calculation to produce an extreme negative number. "
            "ACTION: Flag to developer. This is a known historical issue (Soleil Pegram) "
            "that was previously fixed. If it has re-appeared, the reversal rate "
            "correction logic in reconciliation.py has regressed."
        )

    def test_summary_as_dict(self, db_path):
        from src.etl.pipeline import run_pipeline
        summary = run_pipeline(db_path=db_path)
        d = summary.as_dict()
        assert isinstance(d, dict), (
            "FAIL — PipelineSummary.as_dict() did not return a dict. "
            "This is an internal code error. "
            "ACTION: Flag to developer immediately."
        )
        for key in ("payroll_records", "recon_rows", "result_good",
                    "result_followup", "unmatched_clients"):
            assert key in d, (
                f"FAIL — PipelineSummary.as_dict() is missing key '{key}'. "
                "This is an internal code error that may break the dashboard KPI cards. "
                "ACTION: Flag to developer immediately."
            )

    def test_no_silent_not_billed_when_remittance_exists(self, conn):
        rows = conn.execute("""
            SELECT r.client_name_payroll, r.week_start_date, r.billed_hours, r.care_type
            FROM reconciliation r
            WHERE r.match_status = 'MATCHED'
              AND r.payroll_hours > 0
              AND r.billed_hours = 0
              AND r.paid_hours = 0
              AND r.result_detailed = 'Not Billed'
              AND EXISTS (
                  SELECT 1 FROM remittance rem
                  WHERE rem.client_name_combined = r.client_name_remittance
                    AND rem.is_latest = true
                    AND rem.first_dos <= r.week_end_date
                    AND rem.last_dos >= r.week_start_date
                    AND (
                        CASE
                            WHEN (rem.billed_hours > 0 AND ABS(rem.charge_amount / rem.billed_hours) >= 30.0) THEN 'Skilled'
                            WHEN (rem.paid_hours > 0 AND ABS(rem.payment_amount / rem.paid_hours) >= 30.0) THEN 'Skilled'
                            WHEN (rem.insurance LIKE '%PDN%' OR rem.insurance LIKE '%pdn%') THEN 'Skilled'
                            ELSE 'Unskilled'
                        END
                    ) = r.care_type
              )
        """).fetchall()
        assert len(rows) == 0, (
            f"FAIL — {len(rows)} client(s) are showing 'Not Billed' in reconciliation "
            f"even though a matching remittance record exists for their week and care type: "
            f"{[(r[0], str(r[1]), r[3]) for r in rows[:5]]}. "
            "This is a care-type mismatch bug: the payroll and remittance records exist "
            "but are being joined under different Skilled/Unskilled labels, so they never match. "
            "ACTION: Flag to developer. This is a known historical regression guard "
            "(originally caused by ROBINSON, GEORGE LPN having a suffix-vs-rate mismatch). "
            "Check the care_type column for the listed clients in the reconciliation table."
        )

    def test_dual_care_type_separation(self, conn):
        rows = conn.execute("""
            SELECT week_start_date, COUNT(*)
            FROM reconciliation
            WHERE client_name_payroll LIKE '%DREWRY, KAYLA%'
            GROUP BY week_start_date
            HAVING COUNT(*) > 1
        """).fetchall()
        assert len(rows) > 0, (
            "FAIL — Kayla Drewry should appear in reconciliation with BOTH a Skilled "
            "and an Unskilled entry for at least one week (she has both LPN and PCA hours), "
            "but no such week was found. "
            "ACTION: Check whether Kayla Drewry appears in the current payroll file with "
            "both LPN and PCA rows. If she does, flag to developer — the dual care type "
            "separation logic has regressed. If she only has one type this week, "
            "this test may need its expected client updated."
        )
        for week, count in rows:
            details = conn.execute("""
                SELECT care_type, payroll_hours
                FROM reconciliation
                WHERE client_name_payroll LIKE '%DREWRY, KAYLA%'
                  AND week_start_date = ?
            """, [week]).fetchall()
            care_types = {d[0] for d in details}
            assert care_types == {"Skilled", "Unskilled"}, (
                f"FAIL — For week {week}, Kayla Drewry has {count} reconciliation rows "
                f"but care types are {care_types} instead of {{'Skilled', 'Unskilled'}}. "
                "ACTION: Flag to developer — the care type classification for dual-type "
                "clients is not producing the expected two separate rows."
            )
