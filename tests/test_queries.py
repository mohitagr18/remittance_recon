"""Tests for src/db/queries.py"""

from src.db import queries as q


class TestQueries:
    def test_weekly_summary(self, conn):
        df = q.weekly_summary(conn)
        assert len(df) > 0
        assert "total_clients" in df.columns

    def test_followup_items(self, conn):
        df = q.followup_items(conn)
        assert len(df) > 0

    def test_all_reconciliation(self, conn):
        df = q.all_reconciliation(conn, week_start="2026-02-18")
        assert len(df) == 147

    def test_followup_reason_breakdown(self, conn):
        df = q.followup_reason_breakdown(conn)
        assert len(df) > 0

    def test_payer_collection_rates(self, conn):
        df = q.payer_collection_rates(conn)
        assert len(df) > 0
        assert "insurance" in df.columns

    def test_rolling_trend(self, conn):
        df = q.rolling_trend(conn)
        assert len(df) > 0

    def test_available_weeks(self, conn):
        df = q.available_weeks(conn)
        assert len(df) > 0

    def test_available_insurances(self, conn):
        ins = q.available_insurances(conn)
        assert len(ins) > 0

    def test_all_clients(self, conn):
        clients = q.all_clients(conn)
        assert len(clients) > 0

    def test_get_name_match_table(self, conn):
        df = q.get_name_match_table(conn)
        assert len(df) > 0

    def test_get_copay_table(self, conn):
        df = q.get_copay_table(conn)
        assert len(df) > 0

    def test_client_ledger(self, conn):
        # Find a client in all reconciliation
        recon = q.all_reconciliation(conn)
        client = recon.dropna(subset=["client_name_remittance"]).iloc[0]["client_name_remittance"]
        
        # Test basic ledger retrieval
        df = q.client_ledger(conn, client)
        assert len(df) >= 0

        # Test sorted and filtered retrieval
        df_sorted = q.client_ledger(conn, client, sort_asc=True)
        if len(df_sorted) > 1:
            # Cast first_dos to date if it's datetime for comparison
            import datetime
            d1 = df_sorted.iloc[0]["first_dos"]
            d2 = df_sorted.iloc[-1]["first_dos"]
            d1_val = d1.date() if isinstance(d1, datetime.datetime) else d1
            d2_val = d2.date() if isinstance(d2, datetime.datetime) else d2
            assert d1_val <= d2_val

        # Test unbilled week retrieval
        unbilled_recon = recon[(recon["payroll_hours"] > 0) & (recon["billed_hours"] == 0)]
        if not unbilled_recon.empty:
            client = unbilled_recon.iloc[0]["client_name_payroll"]
            df = q.client_ledger(conn, client)
            week_start = unbilled_recon.iloc[0]["week_start_date"]
            import datetime
            week_start_date = week_start.date() if isinstance(week_start, datetime.datetime) else week_start
            
            # Verify that the unbilled week's start date is returned in df["first_dos"]
            first_dos_dates = [d.date() if isinstance(d, datetime.datetime) else d for d in df["first_dos"].dropna()]
            assert week_start_date in first_dos_dates, f"Unbilled week start date {week_start_date} not found in first_dos for {client}"

    def test_client_weekly_recon_with_dos(self, conn):
        recon = q.all_reconciliation(conn)
        client = recon.dropna(subset=["client_name_payroll"]).iloc[0]["client_name_payroll"]
        df = q.client_weekly_recon_with_dos(conn, client)
        assert len(df) > 0
        assert "first_dos" in df.columns
        assert "pending_hours" in df.columns

    def test_recent_payments(self, conn):
        df = q.recent_payments(conn)
        assert len(df) >= 0
        if len(df) > 0:
            assert "client" in df.columns
            assert "billed_hrs" in df.columns
            assert "paid_hrs" in df.columns
            assert "billed_amt" in df.columns
            assert "paid_amt" in df.columns

    def test_recent_denials(self, conn):
        df = q.recent_denials(conn)
        assert len(df) >= 0
        if len(df) > 0:
            assert "client" in df.columns
            assert "billed_hrs" in df.columns
            assert "paid_hrs" in df.columns
            assert "pending_hrs" in df.columns
            assert "billed_amt" in df.columns
            assert "paid_amt" in df.columns
            assert "amt_delta" in df.columns

    def test_client_ledger_reversal_aggregation(self, conn):
        # Insert test records for a mock client to test reversal aggregation
        client_name = "TEST_REVERSAL_CLIENT"
        
        # Clean up any residual test records first
        conn.execute("DELETE FROM remittance WHERE client_name_combined = ?", [client_name])
        conn.execute("DELETE FROM reconciliation WHERE client_name_remittance = ?", [client_name])
        
        try:
            # Insert a remittance record (Original Payment)
            conn.execute(
                """
                INSERT INTO remittance (
                    id, batch, payment_date, transaction, match_status, claim_number, transaction_type,
                    charge_amount, payment_amount, client_name_combined, first_dos, last_dos, tcn,
                    billed_hours, paid_hours, insurance, is_latest
                ) VALUES (
                    nextval('seq_remittance'), 1, '2026-02-15', 'Original Payment', 'MATCHED', 'CLM001', 'Original',
                    3050.00, 3050.00, ?, '2026-02-04', '2026-02-04', 'TCN001',
                    152.5, 152.5, 'Test Insurance', true
                )
                """,
                [client_name]
            )
            
            # Insert a second remittance record representing a reversal on a later date
            conn.execute(
                """
                INSERT INTO remittance (
                    id, batch, payment_date, transaction, match_status, claim_number, transaction_type,
                    charge_amount, payment_amount, client_name_combined, first_dos, last_dos, tcn,
                    billed_hours, paid_hours, insurance, is_latest
                ) VALUES (
                    nextval('seq_remittance'), 1, '2026-02-20', 'Reversal', 'MATCHED', 'CLM001', 'Denial/Reversal',
                    -3050.00, -3050.00, ?, '2026-02-04', '2026-02-04', 'TCN001-REV',
                    -152.5, -152.5, 'Test Insurance', true
                )
                """,
                [client_name]
            )

            # Insert reconciliation entry to complete the ledger join
            conn.execute(
                """
                INSERT INTO reconciliation (
                    id, week_start_date, week_end_date, client_name_remittance, client_name_payroll,
                    payroll_hours, billed_hours, paid_hours
                ) VALUES (
                    nextval('seq_reconciliation'), '2026-02-01', '2026-02-07', ?, ?,
                    0.0, 152.5, 0.0
                )
                """,
                [client_name, client_name]
            )

            # Call client_ledger on the mock client
            df = q.client_ledger(conn, client_name)
            
            assert len(df) == 1
            # Billed hours should be the maximum (152.5) rather than 0.0
            assert float(df.iloc[0]["billed_hours"]) == 152.5
            # Paid hours should be summed to 0.0
            assert float(df.iloc[0]["paid_hours"]) == 0.0
            
        finally:
            # Clean up the test records
            conn.execute("DELETE FROM remittance WHERE client_name_combined = ?", [client_name])
            conn.execute("DELETE FROM reconciliation WHERE client_name_remittance = ?", [client_name])

    def test_pending_hours_summation(self, conn):
        """
        Verify that total pending hours is calculated by summing weekly client pending hours
        and is not cancelled out by weeks where paid hours exceed payroll hours.
        """
        client_name = "TEST_PENDING_SUMMATION_CLIENT"
        
        # Clean up
        conn.execute("DELETE FROM reconciliation WHERE client_name_payroll = ?", [client_name])
        
        try:
            # Week 1: 10 payroll, 20 paid (overpayment, pending should be 0)
            conn.execute(
                """
                INSERT INTO reconciliation (
                    id, week_start_date, week_end_date, client_name_payroll, client_name_remittance,
                    payroll_hours, billed_hours, paid_hours, result_simple, care_type
                ) VALUES (
                    nextval('seq_reconciliation'), '2026-02-01', '2026-02-07', ?, ?,
                    10.0, 10.0, 20.0, 'Good', 'Unskilled'
                )
                """,
                [client_name, client_name]
            )
            # Week 2: 15 payroll, 0 paid (pending should be 15)
            conn.execute(
                """
                INSERT INTO reconciliation (
                    id, week_start_date, week_end_date, client_name_payroll, client_name_remittance,
                    payroll_hours, billed_hours, paid_hours, result_simple, care_type
                ) VALUES (
                    nextval('seq_reconciliation'), '2026-02-08', '2026-02-14', ?, ?,
                    15.0, 15.0, 0.0, 'Follow up', 'Unskilled'
                )
                """,
                [client_name, client_name]
            )
            
            # 1. Test client_summary pending hours
            summary_df = q.client_summary(conn, client_name, 'Unskilled')
            assert len(summary_df) == 1
            # If the calculation is correct, pending hours should be 15.0 (not 15 - 10 = 5.0)
            assert float(summary_df.iloc[0]["ytd_pending_hrs"]) == 15.0
            
        finally:
            conn.execute("DELETE FROM reconciliation WHERE client_name_payroll = ?", [client_name])





class TestCopayManagement:
    """Tests for copay_management() and upsert_copay_client() queries."""

    def test_copay_management_returns_all_clients(self, conn_with_copay):
        df = q.copay_management(conn_with_copay)
        assert len(df) >= 14

    def test_copay_management_has_required_columns(self, conn_with_copay):
        df = q.copay_management(conn_with_copay)
        for col in ["id", "client_name", "copay_amount", "effective_from", "effective_to", "is_active"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_copay_amounts_loaded_correctly(self, conn_with_copay):
        """Spot-check known copay amounts from whiteboard."""
        df = q.copay_management(conn_with_copay)
        amounts = dict(zip(df["client_name"], df["copay_amount"]))
        assert amounts.get("BUTTS, SHIRLEY")    == 153.00
        assert amounts.get("BUTLER, JANNIE")    == 643.59
        assert amounts.get("BERRYMAN, SHELIAH") == 383.00
        assert amounts.get("RICHEY, MICHAH")    == 749.00
        assert amounts.get("TOWERS, LINDA")     == 1176.00
        assert amounts.get("CLAIBORNE, GEORGE") == 535.00

    def test_new_clients_present(self, conn_with_copay):
        """PEEBLES, LUCY and TRISTVAN-BOTTE, VIVIAN were added from whiteboard."""
        df = q.copay_management(conn_with_copay)
        names = df["client_name"].tolist()
        assert "PEEBLES, LUCY" in names
        assert "TRISTVAN-BOTTE, VIVIAN" in names

    def test_upsert_updates_amount(self, conn_with_copay):
        """upsert_copay_client() updates amount and dates correctly."""
        df = q.copay_management(conn_with_copay)
        butts = df[df["client_name"] == "BUTTS, SHIRLEY"].iloc[0]
        client_id = int(butts["id"])

        # Update to $156.00 — the suspected correct amount from 8-month pattern
        q.upsert_copay_client(
            conn_with_copay, client_id=client_id,
            copay_amount=156.00, effective_from="2025-10-01",
            effective_to=None, is_active=True,
        )
        updated = q.copay_management(conn_with_copay)
        row = updated[updated["client_name"] == "BUTTS, SHIRLEY"].iloc[0]
        assert float(row["copay_amount"]) == 156.00
        assert str(row["effective_from"]).startswith("2025-10-01")

        # Restore original
        q.upsert_copay_client(conn_with_copay, client_id=client_id,
                              copay_amount=153.00, effective_from=None,
                              effective_to=None, is_active=True)

    def test_upsert_sets_inactive(self, conn_with_copay):
        """Setting is_active=False marks client inactive."""
        df = q.copay_management(conn_with_copay)
        peebles = df[df["client_name"] == "PEEBLES, LUCY"].iloc[0]
        client_id = int(peebles["id"])

        q.upsert_copay_client(conn_with_copay, client_id=client_id,
                              copay_amount=174.14, effective_from=None,
                              effective_to=None, is_active=False)
        updated = q.copay_management(conn_with_copay)
        row = updated[updated["client_name"] == "PEEBLES, LUCY"].iloc[0]
        assert row["is_active"] == False

        # Restore
        q.upsert_copay_client(conn_with_copay, client_id=client_id,
                              copay_amount=174.14, effective_from=None,
                              effective_to=None, is_active=True)


class TestCopayMonthlyStatusQuery:
    """Tests for copay_monthly_status() against the real recon.duckdb."""

    def test_returns_dataframe(self, conn_recon):
        df = q.copay_monthly_status(conn_recon)
        assert hasattr(df, "columns")

    def test_required_columns_present(self, conn_recon):
        df = q.copay_monthly_status(conn_recon)
        for col in ["client_name", "copay_amount", "month_label",
                    "total_billed_dollars", "total_paid_dollars",
                    "pending_dollars", "copay_status", "copay_note"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_butler_apr2026_is_copay(self, conn_recon):
        """BUTLER Apr 2026 — pending $643.59 = copay $643.59 → Good / Copay."""
        df = q.copay_monthly_status(conn_recon)
        row = df[(df["client_name"].str.upper() == "BUTLER, JANNIE") &
                 (df["month_label"] == "Apr 2026")]
        assert not row.empty, "BUTLER Apr 2026 not found"
        assert row.iloc[0]["copay_status"] == "Good"
        assert row.iloc[0]["copay_note"] == "Copay"

    def test_cochran_fully_paid_months(self, conn_recon):
        """COCHRAN Jul 2025 — $0 pending → Good / note is None."""
        df = q.copay_monthly_status(conn_recon)
        row = df[(df["client_name"].str.upper() == "COCHRAN, TELEECA") &
                 (df["month_label"] == "Jul 2025")]
        assert not row.empty, "COCHRAN Jul 2025 not found"
        assert row.iloc[0]["copay_status"] == "Good"
        import pandas as pd
        assert pd.isna(row.iloc[0]["copay_note"]) or row.iloc[0]["copay_note"] is None or str(row.iloc[0]["copay_note"]) in ("None", "")

    def test_berryman_apr2025_exceeds_copay(self, conn_recon):
        """BERRYMAN Apr 2025 — pending $1,153.79 > copay $383 → Follow up / Exceeds Copay."""
        df = q.copay_monthly_status(conn_recon)
        row = df[(df["client_name"].str.upper() == "BERRYMAN, SHELIAH") &
                 (df["month_label"] == "Apr 2025")]
        assert not row.empty, "BERRYMAN Apr 2025 not found"
        assert row.iloc[0]["copay_status"] == "Follow up"
        assert row.iloc[0]["copay_note"] == "Exceeds Copay"

    def test_status_values_are_valid(self, conn_recon):
        """All copay_status values must be from the known set."""
        df = q.copay_monthly_status(conn_recon)
        valid = {"Good", "Follow up"}
        assert set(df["copay_status"].dropna().unique()).issubset(valid)

    def test_copay_note_values_are_valid(self, conn_recon):
        """All non-null copay_note values must be from the known set."""
        import pandas as pd
        df = q.copay_monthly_status(conn_recon)
        valid = {"Copay", "Exceeds Copay", "Partial Copay"}
        for val in df["copay_note"].unique():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            assert val in valid, f"Unexpected copay_note value: {val}"
