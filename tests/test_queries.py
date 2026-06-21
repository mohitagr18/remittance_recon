"""Tests for src/db/queries.py — live database integration."""

from src.db import queries as q


class TestQueries:
    def test_weekly_summary(self, conn):
        df = q.weekly_summary(conn)
        assert len(df) > 0, (
            "FAIL — weekly_summary() returned no rows. "
            "This means the reconciliation table is empty or all rows are filtered out. "
            "ACTION: Check that the pipeline has been run (Data Management → Ingest New Files). "
            "If the table has rows but this still fails, check the weekly_summary query filter logic."
        )
        assert "total_clients" in df.columns, (
            f"FAIL — weekly_summary() result is missing the 'total_clients' column. "
            f"Got columns: {list(df.columns)}. "
            "ACTION: Flag to developer — the weekly_summary query has been modified "
            "and no longer returns the expected KPI columns."
        )

    def test_followup_items(self, conn):
        df = q.followup_items(conn)
        assert len(df) > 0, (
            "FAIL — followup_items() returned no rows. "
            "This could be correct (no Follow up items exist) or it could mean "
            "the filter is too restrictive. "
            "ACTION: Check the Weekly Reconciliation view in the dashboard. "
            "If Follow up rows are visible there but not here, flag to developer."
        )

    def test_all_reconciliation(self, conn):
        df = q.all_reconciliation(conn, week_start="2026-02-18")
        assert len(df) == 147, (
            f"FAIL — all_reconciliation() for week 2026-02-18 returned {len(df)} rows, "
            "expected 147. "
            "This week's reconciliation row count has changed. "
            "Possible causes:\n"
            "  • New payroll or remittance data was ingested that adds/removes rows for this week\n"
            "  • The name match mapping changed, affecting how many clients are matched\n"
            "  • A reconciliation rebuild changed how rows are counted\n"
            "NOTE: If a new file was intentionally ingested that changes this week's data, "
            "update the expected count in this test to match the new correct value. "
            "ACTION: Go to Weekly Reconciliation, filter to week 2026-02-18, and count the rows. "
            "Update the assertion if the new count is intentional."
        )

    def test_followup_reason_breakdown(self, conn):
        df = q.followup_reason_breakdown(conn)
        assert len(df) > 0, (
            "FAIL — followup_reason_breakdown() returned no rows. "
            "This means either no Follow up rows exist, or the grouping query has broken. "
            "ACTION: If follow-up items exist in the dashboard, flag to developer."
        )

    def test_payer_collection_rates(self, conn):
        df = q.payer_collection_rates(conn)
        assert len(df) > 0, (
            "FAIL — payer_collection_rates() returned no rows. "
            "ACTION: Confirm the remittance table has data with non-null insurance values. "
            "If yes, flag to developer."
        )
        assert "insurance" in df.columns, (
            f"FAIL — payer_collection_rates() missing 'insurance' column. "
            f"Got: {list(df.columns)}. "
            "ACTION: Flag to developer — query has been modified."
        )

    def test_rolling_trend(self, conn):
        df = q.rolling_trend(conn)
        assert len(df) > 0, (
            "FAIL — rolling_trend() returned no rows. "
            "This query aggregates reconciliation by week. "
            "ACTION: Confirm the reconciliation table has data, then flag to developer if so."
        )

    def test_available_weeks(self, conn):
        weeks = q.available_weeks(conn)
        assert len(weeks) > 0, (
            "FAIL — available_weeks() returned no weeks. "
            "The reconciliation table appears to have no week_start_date values. "
            "ACTION: Check that the pipeline has run and reconciliation rows exist."
        )

    def test_available_insurances(self, conn):
        ins = q.available_insurances(conn)
        assert len(ins) > 0, (
            "FAIL — available_insurances() returned no values. "
            "The reconciliation table has no insurance column values. "
            "ACTION: Check that the remittance data has been ingested with insurance labels."
        )

    def test_all_clients(self, conn):
        clients = q.all_clients(conn)
        assert len(clients) > 0, (
            "FAIL — all_clients() returned no clients. "
            "ACTION: Confirm payroll and/or reconciliation data exists in the database."
        )

    def test_get_name_match_table(self, conn):
        df = q.get_name_match_table(conn)
        assert len(df) > 0, (
            "FAIL — get_name_match_table() returned no rows. "
            "The name_match table is empty. "
            "ACTION: Check that the Weekly Recon Excel file has a populated 'Name Match' sheet "
            "and that the pipeline was run after that file was placed in the input directory."
        )

    def test_get_copay_table(self, conn):
        df = q.get_copay_table(conn)
        assert len(df) > 0, (
            "FAIL — get_copay_table() returned no rows. "
            "The copay_clients table is empty. "
            "ACTION: Check that the Weekly Recon Excel file has a populated 'Copay' sheet "
            "and that the pipeline was run after the recon file was placed in the input directory."
        )

    def test_client_ledger(self, conn):
        recon = q.all_reconciliation(conn)
        client = recon.dropna(subset=["client_name_remittance"]).iloc[0]["client_name_remittance"]
        df = q.client_ledger(conn, client)
        assert len(df) >= 0, (
            "FAIL — client_ledger() raised an error. "
            f"Client tested: {client!r}. "
            "ACTION: Flag to developer."
        )
        df_sorted = q.client_ledger(conn, client, sort_asc=True)
        if len(df_sorted) > 1:
            import datetime
            d1 = df_sorted.iloc[0]["first_dos"]
            d2 = df_sorted.iloc[-1]["first_dos"]
            d1 = d1.date() if isinstance(d1, datetime.datetime) else d1
            d2 = d2.date() if isinstance(d2, datetime.datetime) else d2
            assert d1 <= d2, (
                f"FAIL — client_ledger(sort_asc=True) is not sorted ascending. "
                f"First date: {d1}, last date: {d2}. "
                "ACTION: Flag to developer — sort order in client_ledger() has broken."
            )

    def test_client_weekly_recon_with_dos(self, conn):
        recon = q.all_reconciliation(conn)
        client = recon.dropna(subset=["client_name_payroll"]).iloc[0]["client_name_payroll"]
        df = q.client_weekly_recon_with_dos(conn, client)
        assert len(df) > 0, (
            f"FAIL — client_weekly_recon_with_dos() returned no rows for client {client!r}. "
            "ACTION: Flag to developer — the query may have an incorrect join condition."
        )
        for col in ("first_dos", "pending_hours"):
            assert col in df.columns, (
                f"FAIL — client_weekly_recon_with_dos() missing column '{col}'. "
                f"Got: {list(df.columns)}. "
                "ACTION: Flag to developer — query has been modified."
            )

    def test_recent_payments(self, conn):
        df = q.recent_payments(conn)
        if len(df) > 0:
            for col in ("client", "billed_hrs", "paid_hrs", "billed_amt", "paid_amt"):
                assert col in df.columns, (
                    f"FAIL — recent_payments() missing column '{col}'. "
                    f"Got: {list(df.columns)}. "
                    "ACTION: Flag to developer — query output schema has changed."
                )

    def test_recent_denials(self, conn):
        df = q.recent_denials(conn)
        if len(df) > 0:
            assert "client" in df.columns, (
                f"FAIL — recent_denials() missing 'client' column. "
                f"Got: {list(df.columns)}. "
                "ACTION: Flag to developer."
            )



class TestCopayMonthlyStatusQuery:
    """Tests for copay_monthly_status() against the real recon.duckdb."""

    def test_returns_dataframe(self, conn_recon):
        df = q.copay_monthly_status(conn_recon)
        assert hasattr(df, "columns"), (
            "FAIL — copay_monthly_status() did not return a DataFrame. "
            "ACTION: Flag to developer — internal query error."
        )

    def test_required_columns_present(self, conn_recon):
        df = q.copay_monthly_status(conn_recon)
        required = ["client_name", "copay_amount", "month_label",
                    "total_billed_dollars", "total_paid_dollars",
                    "pending_dollars", "copay_status", "copay_note"]
        missing = [c for c in required if c not in df.columns]
        assert not missing, (
            f"FAIL — copay_monthly_status() is missing columns: {missing}. "
            f"Got columns: {list(df.columns)}. "
            "ACTION: Flag to developer — the copay_monthly_status query schema has changed."
        )

    def test_butler_apr2026_is_copay(self, conn_recon):
        """BUTLER Apr 2026 — pending $643.59 = copay $643.59 → Good / Copay."""
        df = q.copay_monthly_status(conn_recon)
        row = df[(df["client_name"].str.upper() == "BUTLER, JANNIE") &
                 (df["month_label"] == "Apr 2026")]
        assert not row.empty, (
            "FAIL — BUTLER, JANNIE Apr 2026 not found in copay_monthly_status(). "
            "This client is a known copay client (amount: $643.59). "
            "ACTION: Check that BUTLER, JANNIE is in the copay_clients table "
            "with copay_amount set. Go to Admin → Copay Manager to verify."
        )
        assert row.iloc[0]["copay_status"] == "Good", (
            f"FAIL — BUTLER Apr 2026 expected status 'Good' (pending matches copay), "
            f"got '{row.iloc[0]['copay_status']}'. "
            "ACTION: Verify BUTLER, JANNIE copay_amount is $643.59 in Copay Manager."
        )
        assert row.iloc[0]["copay_note"] == "Copay", (
            f"FAIL — BUTLER Apr 2026 expected note 'Copay', got '{row.iloc[0]['copay_note']}'. "
            "ACTION: Flag to developer — copay note classification logic may have changed."
        )

    def test_cochran_fully_paid_months(self, conn_recon):
        """COCHRAN Jul 2025 — $0 pending → Good / no note."""
        df = q.copay_monthly_status(conn_recon)
        row = df[(df["client_name"].str.upper() == "COCHRAN, TELEECA") &
                 (df["month_label"] == "Jul 2025")]
        assert not row.empty, (
            "FAIL — COCHRAN, TELEECA Jul 2025 not found in copay_monthly_status(). "
            "ACTION: Check that COCHRAN, TELEECA is in the copay_clients table."
        )
        assert row.iloc[0]["copay_status"] == "Good", (
            f"FAIL — COCHRAN Jul 2025 expected 'Good' (fully paid), "
            f"got '{row.iloc[0]['copay_status']}'. "
            "ACTION: Verify the remittance data for COCHRAN, TELEECA Jul 2025 shows "
            "pending_dollars = 0 or within tolerance."
        )

    def test_berryman_apr2025_exceeds_copay(self, conn_recon):
        """BERRYMAN Apr 2025 — pending $1,153.79 > copay $383 → Follow up / Exceeds Copay."""
        df = q.copay_monthly_status(conn_recon)
        row = df[(df["client_name"].str.upper() == "BERRYMAN, SHELIAH") &
                 (df["month_label"] == "Apr 2025")]
        assert not row.empty, (
            "FAIL — BERRYMAN, SHELIAH Apr 2025 not found in copay_monthly_status(). "
            "ACTION: Check that BERRYMAN, SHELIAH is in the copay_clients table."
        )
        assert row.iloc[0]["copay_status"] == "Follow up", (
            f"FAIL — BERRYMAN Apr 2025 expected 'Follow up' (pending > copay), "
            f"got '{row.iloc[0]['copay_status']}'. "
            "The pending amount for this month exceeds the $383 copay threshold. "
            "ACTION: Flag to developer — copay status classification logic has changed."
        )
        assert row.iloc[0]["copay_note"] == "Exceeds Copay", (
            f"FAIL — BERRYMAN Apr 2025 expected note 'Exceeds Copay', "
            f"got '{row.iloc[0]['copay_note']}'. "
            "ACTION: Flag to developer."
        )

    def test_status_values_are_valid(self, conn_recon):
        df = q.copay_monthly_status(conn_recon)
        valid = {"Good", "Follow up"}
        invalid = set(df["copay_status"].dropna().unique()) - valid
        assert not invalid, (
            f"FAIL — Unexpected copay_status value(s): {invalid}. "
            f"Valid values are: {valid}. "
            "ACTION: Flag to developer — a new status value has been introduced "
            "that the Copay Manager UI does not handle."
        )

    def test_copay_note_values_are_valid(self, conn_recon):
        import pandas as pd
        df = q.copay_monthly_status(conn_recon)
        valid = {"Copay", "Exceeds Copay", "Partial Copay"}
        invalid = {v for v in df["copay_note"].unique()
                   if v is not None and not (isinstance(v, float) and pd.isna(v))
                   and v not in valid}
        assert not invalid, (
            f"FAIL — Unexpected copay_note value(s): {invalid}. "
            f"Valid values are: {valid}. "
            "ACTION: Flag to developer — a new note value has been introduced."
        )


class TestCopayManagement:
    """Tests for copay_management() and upsert_copay_client() queries."""

    def test_copay_management_returns_all_clients(self, conn_with_copay):
        df = q.copay_management(conn_with_copay)
        assert len(df) >= 14, (
            f"FAIL — copay_management() returned {len(df)} rows, expected at least 14. "
            "The copay_clients table has fewer clients than expected. "
            "ACTION: Go to Admin → Copay Manager and verify that all known copay clients "
            "are listed. If clients are missing, add them via the Copay Manager UI."
        )

    def test_copay_management_has_required_columns(self, conn_with_copay):
        df = q.copay_management(conn_with_copay)
        required = ["id", "client_name", "copay_amount", "effective_from",
                    "effective_to", "is_active"]
        missing = [c for c in required if c not in df.columns]
        assert not missing, (
            f"FAIL — copay_management() missing columns: {missing}. "
            f"Got: {list(df.columns)}. "
            "ACTION: Flag to developer — copay schema has changed."
        )

    def test_copay_amounts_loaded_correctly(self, conn_with_copay):
        """Spot-check known copay amounts."""
        df = q.copay_management(conn_with_copay)
        amounts = dict(zip(df["client_name"], df["copay_amount"]))
        checks = {
            "BUTTS, SHIRLEY":     153.00,
            "BUTLER, JANNIE":     643.59,
            "BERRYMAN, SHELIAH":  383.00,
            "RICHEY, MICHAH":     749.00,
            "TOWERS, LINDA":     1176.00,
            "CLAIBORNE, GEORGE":  535.00,
        }
        wrong = [(name, expected, amounts.get(name))
                 for name, expected in checks.items()
                 if amounts.get(name) != expected]
        assert not wrong, (
            f"FAIL — Copay amounts do not match expected values: "
            f"{[(n, f'expected {e}, got {g}') for n, e, g in wrong]}. "
            "ACTION: Go to Admin → Copay Manager and correct the amounts. "
            "These values come from the Copay sheet in the Weekly Recon Excel file."
        )

    def test_new_clients_present(self, conn_with_copay):
        df = q.copay_management(conn_with_copay)
        names = df["client_name"].tolist()
        missing = [n for n in ("PEEBLES, LUCY", "TRISTVAN-BOTTE, VIVIAN") if n not in names]
        assert not missing, (
            f"FAIL — Expected copay clients not found: {missing}. "
            "These clients were added from the whiteboard list. "
            "ACTION: Go to Admin → Copay Manager and manually add the missing client(s)."
        )

    def test_upsert_updates_amount(self, conn_with_copay):
        """upsert_copay_client() updates amount and dates correctly."""
        df = q.copay_management(conn_with_copay)
        butts = df[df["client_name"] == "BUTTS, SHIRLEY"].iloc[0]
        client_id = int(butts["id"])
        q.upsert_copay_client(
            conn_with_copay, client_id=client_id,
            copay_amount=156.00, effective_from="2025-10-01",
            effective_to=None, is_active=True,
        )
        df2 = q.copay_management(conn_with_copay)
        updated = df2[df2["client_name"] == "BUTTS, SHIRLEY"].iloc[0]
        assert float(updated["copay_amount"]) == 156.00, (
            f"FAIL — upsert_copay_client() did not update copay_amount. "
            f"Expected 156.00, got {updated['copay_amount']}. "
            "ACTION: Flag to developer — the upsert query is not writing correctly."
        )
