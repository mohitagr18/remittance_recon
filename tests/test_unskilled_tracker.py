"""
Tests for Unskilled Tracker overrides, volume/age escalation rules, and downstream query propagation.
"""

from datetime import date, datetime
import pytest
import duckdb
import pandas as pd

from src.db.schema import create_all
from src.db import queries as q
from src.db import unskilled_tracker_queries as utq


class TestUnskilledTrackerOverrides:

    @pytest.fixture(autouse=True)
    def setup_conn(self):
        """Isolated in-memory connection for testing."""
        self.conn = duckdb.connect()
        create_all(self.conn)
        yield
        self.conn.close()

    def test_schema_columns_present(self):
        """Ensure all override and workflow columns are present in the table schema."""
        info = self.conn.execute("PRAGMA table_info('unskilled_remit_tracker')").fetchall()
        columns = {row[1] for row in info}
        
        expected = {
            "override",
            "override_reason",
            "overridden_by",
            "override_date",
            "notes",
            "follow_up_date",
            "resolved"
        }
        missing = expected - columns
        assert not missing, f"Missing columns in database schema: {missing}"

    def test_sync_and_escalation_rules(self):
        """Test volume and age escalation rules under override conditions."""
        # 1. Seed reconciliation data for client Veronica Lewis (Unskilled)
        # We need 5 entries within a 2-month rolling window to trigger volume escalation
        dos_dates = [
            ("2026-01-01", "2026-01-07"),
            ("2026-01-08", "2026-01-14"),
            ("2026-01-15", "2026-01-21"),
            ("2026-01-22", "2026-01-28"),
            ("2026-02-01", "2026-02-07"),  # 5th entry
            ("2026-02-08", "2026-02-14"),  # 6th entry
        ]
        
        for i, (start, end) in enumerate(dos_dates):
            self.conn.execute("""
                INSERT INTO reconciliation (
                    id, week_start_date, week_end_date, paycheck_date, insurance,
                    client_name_payroll, client_name_remittance, payroll_hours, billed_hours, paid_hours,
                    result_simple, result_detailed, care_type
                ) VALUES (?, CAST(? AS DATE), CAST(? AS DATE), CURRENT_DATE, 'Humana',
                          'Veronica Lewis', 'LEWIS, VERONICA', 40.0, 40.0, 0.0,
                          'Follow up', 'Paid Less', 'Unskilled')
            """, [100 + i, start, end])
            
        # Run sync and check that we have 6 pending rows
        utq.sync_pending_from_reconciliation(self.conn)
        pending = utq.get_pending_df(self.conn)
        assert len(pending) == 6
        
        # Refresh escalation flags and verify client is escalated (VOLUME)
        utq.refresh_escalation_flags(self.conn)
        pending = utq.get_pending_df(self.conn)
        assert pending["is_escalated"].all()
        assert (pending["status"] == "ESCALATED").all()
        
        # 2. Apply override to 3 entries so only 3 non-overridden entries remain
        # This should bring the active open count down to 3 (< 5), resolving the volume escalation.
        overridden_ids = pending["id"].iloc[:3].tolist()
        for tid in overridden_ids:
            self.conn.execute("""
                UPDATE unskilled_remit_tracker
                SET override = TRUE,
                    override_reason = 'Humana - confirmed paid',
                    overridden_by = 'analyst',
                    override_date = CURRENT_DATE
                WHERE id = ?
            """, [int(tid)])
        self.conn.commit()
        
        # Refresh escalation flags and verify escalation is resolved
        utq.refresh_escalation_flags(self.conn)
        pending = utq.get_pending_df(self.conn)
        
        # Non-overridden rows should now be PENDING, not ESCALATED
        active_pending = pending[pending["override"] == False]
        assert not active_pending["is_escalated"].any()
        assert (active_pending["status"] == "PENDING").all()
        
    def test_age_escalation_uses_first_dos(self):
        """Verify age escalation is computed based on first_dos and ignores entry_date."""
        # Seed an item with first_dos 11 months ago, but entry_date today
        # Age limit is 10 months, so this should trigger age escalation
        first_dos_past = "2025-07-01"
        last_dos_past = "2025-07-07"
        
        self.conn.execute("""
            INSERT INTO reconciliation (
                id, week_start_date, week_end_date, paycheck_date, insurance,
                client_name_payroll, client_name_remittance, payroll_hours, billed_hours, paid_hours,
                result_simple, result_detailed, care_type
            ) VALUES (?, CAST(? AS DATE), CAST(? AS DATE), CURRENT_DATE, 'Humana',
                      'Veronica Lewis', 'LEWIS, VERONICA', 40.0, 40.0, 0.0,
                      'Follow up', 'Paid Less', 'Unskilled')
        """, [200, first_dos_past, last_dos_past])
        
        utq.sync_pending_from_reconciliation(self.conn)
        
        # Age calculation in queries should run and flag it
        utq.refresh_escalation_flags(self.conn)
        pending = utq.get_pending_df(self.conn)
        assert len(pending) == 1
        assert pending["is_escalated"].iloc[0] == True
        assert pending["escalation_reason"].iloc[0] == "AGE"
        
        # Check that override resolves the age escalation
        self.conn.execute("UPDATE unskilled_remit_tracker SET override = TRUE, override_reason = 'Testing age' WHERE id = ?", [int(pending["id"].iloc[0])])
        self.conn.commit()
        
        utq.refresh_escalation_flags(self.conn)
        pending = utq.get_pending_df(self.conn)
        # It's overridden, so it should not be escalated
        overridden_row = pending[pending["id"] == pending["id"].iloc[0]]
        assert not overridden_row["is_escalated"].iloc[0]

    def test_kpis_exclude_overridden(self):
        """Ensure get_kpis() excludes overridden entries from open/pending totals."""
        self.conn.execute("""
            INSERT INTO reconciliation (
                id, week_start_date, week_end_date, paycheck_date, insurance,
                client_name_payroll, client_name_remittance, payroll_hours, billed_hours, paid_hours,
                result_simple, result_detailed, care_type
            ) VALUES (301, '2026-01-01', '2026-01-07', CURRENT_DATE, 'Humana',
                      'Veronica Lewis', 'LEWIS, VERONICA', 40.0, 40.0, 0.0,
                      'Follow up', 'Paid Less', 'Unskilled')
        """)
        utq.sync_pending_from_reconciliation(self.conn)
        
        # Initial KPIs
        kpis_before = utq.get_kpis(self.conn)
        assert kpis_before["total_open"] == 1
        assert kpis_before["total_pending_hours"] == 40.0
        
        # Override the item
        row_id = int(self.conn.execute("SELECT id FROM unskilled_remit_tracker").fetchone()[0])
        self.conn.execute("UPDATE unskilled_remit_tracker SET override = TRUE WHERE id = ?", [row_id])
        self.conn.commit()
        
        kpis_after = utq.get_kpis(self.conn)
        assert kpis_after["total_open"] == 0
        assert kpis_after["total_pending_hours"] == 0.0

    def test_downstream_propagation(self):
        """Verify that overrides propagate to client summaries, copay manager, and ledgers."""
        # Seed 1 week of payroll and reconciliation for copay client
        self.conn.execute("""
            INSERT INTO copay_clients (id, client_name, is_active, copay_amount)
            VALUES (900, 'Veronica Lewis', TRUE, 100.00)
        """)
        self.conn.execute("""
            INSERT INTO reconciliation (
                id, week_start_date, week_end_date, paycheck_date, insurance,
                client_name_payroll, client_name_remittance, payroll_hours, billed_hours, paid_hours,
                result_simple, result_detailed, care_type
            ) VALUES (401, '2026-05-01', '2026-05-07', CURRENT_DATE, 'Humana',
                      'Veronica Lewis', 'LEWIS, VERONICA', 10.0, 10.0, 0.0,
                      'Follow up', 'Paid Less', 'Unskilled')
        """)
        # We also need a remittance record to compute hourly rates for copay
        self.conn.execute("""
            INSERT INTO remittance (
                id, first_dos, last_dos, payment_date, transaction, match_status,
                tcn, transaction_type, charge_amount, payment_amount, allowed_amount,
                client_name_combined, billed_hours, paid_hours, insurance, is_latest
            ) VALUES (999999, '2026-05-01', '2026-05-07', '2026-05-15', 'T123', 'MATCHED',
                      'T123', 'Payment', 350.00, 350.00, 350.00, 'LEWIS, VERONICA', 10.0, 10.0, 'Humana', TRUE)
        """)
        self.conn.commit()

        utq.sync_pending_from_reconciliation(self.conn)
        
        # Set override
        self.conn.execute("""
            UPDATE unskilled_remit_tracker
            SET override = TRUE, override_reason = 'Confirmed paid'
        """)
        self.conn.commit()
        
        # 1. Summary details should reflect 0 pending hours
        summary = q.client_summary(self.conn, "Veronica Lewis")
        assert len(summary) > 0
        assert summary.iloc[0]["ytd_pending_hrs"] == 0.0
        assert summary.iloc[0]["followup_weeks"] == 0

        # 2. Client weekly recon with DOS should reflect 0 pending hours
        weekly = q.client_weekly_recon_with_dos(self.conn, "Veronica Lewis")
        assert len(weekly) > 0
        assert weekly.iloc[0]["pending_hours"] == 0.0

        # 3. Copay monthly status shortfall should exclude the overridden week
        # (resulting in 0 shortfall and status Good instead of Follow up)
        copay_status = q.copay_monthly_status(self.conn, year=2026, month=5)
        # Since the week is overridden, it is filtered out completely from the month's hours,
        # so Veronica Lewis should have no entry or 0 pending dollars for May 2026
        # Let's verify:
        lewis_copay = copay_status[copay_status["client_name"] == "Veronica Lewis"]
        assert lewis_copay.empty
