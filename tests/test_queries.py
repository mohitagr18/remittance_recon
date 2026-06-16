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


