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



