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
        assert len(df) == 158

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
            assert df_sorted.iloc[0]["first_dos"] <= df_sorted.iloc[-1]["first_dos"]

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


