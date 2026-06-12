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
        df = q.all_reconciliation(conn)
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
