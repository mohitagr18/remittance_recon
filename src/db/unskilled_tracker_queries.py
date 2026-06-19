"""
src/db/unskilled_tracker_queries.py
All DB read/write operations for the Unskilled Remittance Tracker.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import duckdb
import pandas as pd


# ── Config helpers ─────────────────────────────────────────────────────────────

def get_config(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Return all system_config rows as a plain dict."""
    rows = conn.execute("SELECT key, value FROM system_config").fetchall()
    return {k: v for k, v in rows}


def _threshold(conn: duckdb.DuckDBPyConnection) -> float:
    cfg = get_config(conn)
    return float(cfg.get("RESOLVED_HOURS_THRESHOLD", 2))


def _escalation_count(conn: duckdb.DuckDBPyConnection) -> int:
    cfg = get_config(conn)
    return int(cfg.get("ESCALATION_ENTRY_COUNT", 5))


def _escalation_age_months(conn: duckdb.DuckDBPyConnection) -> int:
    cfg = get_config(conn)
    return int(cfg.get("ESCALATION_AGE_MONTHS", 10))


# ── Auto-population from payroll/remittance ────────────────────────────────────

def sync_pending_from_reconciliation(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Create new unskilled_remit_tracker rows for any reconciliation record where:
      - care_type = 'Unskilled'
      - result_simple indicates a follow-up is needed (Paid Less / Not Billed / Billed Short)
      - no tracker row already exists for that client+payer+DOS combination

    Returns count of newly inserted rows.
    """
    inserted = conn.execute("""
        INSERT INTO unskilled_remit_tracker (
            id, client_name, payer, first_dos, last_dos,
            regular_hours, respite_hours, pending_hours,
            status, entry_date, created_at, updated_at
        )
        SELECT
            nextval('seq_unskilled_remit_tracker'),
            r.client_name_payroll,
            r.insurance,
            r.week_start_date,
            r.week_end_date,
            r.payroll_hours,
            0,                          -- respite_hours placeholder; updated below
            r.payroll_hours - COALESCE(r.paid_hours, 0),
            CASE
                WHEN (r.payroll_hours - COALESCE(r.paid_hours, 0)) < 2 THEN 'RESOLVED'
                WHEN COALESCE(r.paid_hours, 0) > 0                    THEN 'PARTIAL'
                ELSE 'PENDING'
            END,
            CURRENT_DATE,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM reconciliation r
        WHERE r.care_type = 'Unskilled'
          AND r.result_simple IN ('Follow up', 'Paid Less', 'Not Billed', 'Billed Short')
          AND NOT EXISTS (
              SELECT 1 FROM unskilled_remit_tracker t
              WHERE t.client_name = r.client_name_payroll
                AND t.payer       = r.insurance
                AND t.first_dos   = r.week_start_date
                AND t.last_dos    = r.week_end_date
          )
        ON CONFLICT DO NOTHING
    """).rowcount
    conn.commit()
    return inserted or 0


def sync_payments_from_remittance(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Update pending_hours on all open tracker rows by matching against the
    latest remittance data (client_name_combined + first_dos + last_dos).

    - Deducts paid_hours from the remittance table.
    - If pending_hours < RESOLVED_HOURS_THRESHOLD → stamps payment_date + sets RESOLVED.
    - Returns count of rows updated.
    """
    threshold = _threshold(conn)
    updated = conn.execute("""
        UPDATE unskilled_remit_tracker AS t
        SET
            pending_hours = GREATEST(
                0,
                (t.regular_hours + t.respite_hours) -
                COALESCE((
                    SELECT SUM(rem.paid_hours)
                    FROM remittance rem
                    JOIN name_match nm
                        ON LOWER(TRIM(rem.client_name_combined)) = LOWER(TRIM(nm.remittance_name))
                    WHERE LOWER(TRIM(nm.payroll_name)) = LOWER(TRIM(t.client_name))
                      AND rem.first_dos  = t.first_dos
                      AND rem.last_dos   = t.last_dos
                      AND rem.insurance  = t.payer
                ), 0)
            ),
            status = CASE
                WHEN GREATEST(
                    0,
                    (t.regular_hours + t.respite_hours) -
                    COALESCE((
                        SELECT SUM(rem.paid_hours)
                        FROM remittance rem
                        JOIN name_match nm
                            ON LOWER(TRIM(rem.client_name_combined)) = LOWER(TRIM(nm.remittance_name))
                        WHERE LOWER(TRIM(nm.payroll_name)) = LOWER(TRIM(t.client_name))
                          AND rem.first_dos  = t.first_dos
                          AND rem.last_dos   = t.last_dos
                          AND rem.insurance  = t.payer
                    ), 0)
                ) < ? THEN 'RESOLVED'
                WHEN COALESCE((
                    SELECT SUM(rem.paid_hours)
                    FROM remittance rem
                    JOIN name_match nm
                        ON LOWER(TRIM(rem.client_name_combined)) = LOWER(TRIM(nm.remittance_name))
                    WHERE LOWER(TRIM(nm.payroll_name)) = LOWER(TRIM(t.client_name))
                      AND rem.first_dos  = t.first_dos
                      AND rem.last_dos   = t.last_dos
                      AND rem.insurance  = t.payer
                ), 0) > 0 THEN 'PARTIAL'
                ELSE t.status
            END,
            payment_date = CASE
                WHEN GREATEST(
                    0,
                    (t.regular_hours + t.respite_hours) -
                    COALESCE((
                        SELECT SUM(rem.paid_hours)
                        FROM remittance rem
                        JOIN name_match nm
                            ON LOWER(TRIM(rem.client_name_combined)) = LOWER(TRIM(nm.remittance_name))
                        WHERE LOWER(TRIM(nm.payroll_name)) = LOWER(TRIM(t.client_name))
                          AND rem.first_dos  = t.first_dos
                          AND rem.last_dos   = t.last_dos
                          AND rem.insurance  = t.payer
                    ), 0)
                ) < ? THEN CURRENT_DATE
                ELSE t.payment_date
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE t.status != 'RESOLVED'
    """, [threshold, threshold]).rowcount
    conn.commit()
    return updated or 0


def refresh_escalation_flags(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Recompute is_escalated and escalation_reason for all non-resolved rows.
    Two triggers:
      - VOLUME : client has >= ESCALATION_ENTRY_COUNT open entries
      - AGE    : entry_date is >= ESCALATION_AGE_MONTHS months ago
    """
    count_threshold = _escalation_count(conn)
    age_months = _escalation_age_months(conn)

    conn.execute("""
        UPDATE unskilled_remit_tracker AS t
        SET
            is_escalated = (
                volume_flag OR age_flag
            ),
            escalation_reason = CASE
                WHEN volume_flag AND age_flag THEN 'VOLUME,AGE'
                WHEN volume_flag              THEN 'VOLUME'
                WHEN age_flag                 THEN 'AGE'
                ELSE NULL
            END,
            status = CASE
                WHEN (volume_flag OR age_flag) AND t.status != 'RESOLVED' THEN 'ESCALATED'
                WHEN NOT (volume_flag OR age_flag) AND t.status = 'ESCALATED' THEN 'PENDING'
                ELSE t.status
            END,
            updated_at = CURRENT_TIMESTAMP
        FROM (
            SELECT
                id,
                (COUNT(*) OVER (PARTITION BY client_name) >= ?) AS volume_flag,
                (DATEDIFF('month', entry_date, CURRENT_DATE) >= ?)  AS age_flag
            FROM unskilled_remit_tracker
            WHERE status != 'RESOLVED'
        ) flags
        WHERE t.id = flags.id
          AND t.status != 'RESOLVED'
    """, [count_threshold, age_months])
    conn.commit()


# ── Read queries ───────────────────────────────────────────────────────────────

def get_pending_df(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """All non-resolved rows with comment count joined."""
    return conn.execute("""
        SELECT
            t.id,
            t.client_name,
            t.payer,
            t.first_dos,
            t.last_dos,
            t.regular_hours,
            t.respite_hours,
            t.pending_hours,
            t.rebill1_date,
            t.rebill1_hours,
            t.rebill2_date,
            t.rebill2_hours,
            t.rebill3_date,
            t.rebill3_hours,
            t.status,
            t.is_escalated,
            t.escalation_reason,
            t.entry_date,
            t.updated_at,
            COALESCE(c.comment_count, 0) AS comment_count
        FROM unskilled_remit_tracker t
        LEFT JOIN (
            SELECT tracker_id, COUNT(*) AS comment_count
            FROM unskilled_remit_comments
            GROUP BY tracker_id
        ) c ON c.tracker_id = t.id
        WHERE t.status != 'RESOLVED'
        ORDER BY t.is_escalated DESC, t.entry_date ASC
    """).df()


def get_resolved_df(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """All resolved rows."""
    return conn.execute("""
        SELECT
            t.id,
            t.client_name,
            t.payer,
            t.first_dos,
            t.last_dos,
            t.regular_hours,
            t.respite_hours,
            t.rebill1_date, t.rebill1_hours,
            t.rebill2_date, t.rebill2_hours,
            t.rebill3_date, t.rebill3_hours,
            t.payment_date,
            t.entry_date,
            t.updated_at
        FROM unskilled_remit_tracker t
        WHERE t.status = 'RESOLVED'
        ORDER BY t.payment_date DESC
    """).df()


def get_comments(conn: duckdb.DuckDBPyConnection, tracker_id: int) -> pd.DataFrame:
    """All comments for a single tracker row, oldest first."""
    return conn.execute("""
        SELECT author, comment_text, created_at
        FROM unskilled_remit_comments
        WHERE tracker_id = ?
        ORDER BY created_at ASC
    """, [tracker_id]).df()


def get_kpis(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Aggregate KPIs for the executive dashboard."""
    row = conn.execute("""
        SELECT
            COUNT(*)                                               AS total_open,
            COALESCE(SUM(pending_hours), 0)                        AS total_pending_hours,
            COUNT(*) FILTER (WHERE is_escalated)                   AS escalated_count,
            COALESCE(AVG(DATEDIFF('day', entry_date, CURRENT_DATE)), 0) AS avg_days_open,
            COUNT(*) FILTER (WHERE status = 'PARTIAL')             AS partial_count
        FROM unskilled_remit_tracker
        WHERE status != 'RESOLVED'
    """).fetchone()

    resolved_this_month = conn.execute("""
        SELECT COUNT(*) FROM unskilled_remit_tracker
        WHERE status = 'RESOLVED'
          AND YEAR(payment_date)  = YEAR(CURRENT_DATE)
          AND MONTH(payment_date) = MONTH(CURRENT_DATE)
    """).fetchone()[0]

    return {
        "total_open": int(row[0]),
        "total_pending_hours": float(row[1]),
        "escalated_count": int(row[2]),
        "avg_days_open": round(float(row[3]), 1),
        "partial_count": int(row[4]),
        "resolved_this_month": int(resolved_this_month),
    }


def get_escalation_by_client(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Clients with volume or age escalation — grouped summary."""
    return conn.execute("""
        SELECT
            client_name,
            payer,
            COUNT(*)                                   AS open_entries,
            COALESCE(SUM(pending_hours), 0)            AS total_pending_hours,
            MIN(entry_date)                            AS oldest_entry,
            DATEDIFF('day', MIN(entry_date), CURRENT_DATE) AS days_outstanding,
            STRING_AGG(DISTINCT escalation_reason, ', ') AS reasons
        FROM unskilled_remit_tracker
        WHERE is_escalated = TRUE AND status != 'RESOLVED'
        GROUP BY client_name, payer
        ORDER BY days_outstanding DESC
    """).df()


def get_aged_items(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Individual rows that are age-escalated, oldest first."""
    age_months = _escalation_age_months(conn)
    return conn.execute("""
        SELECT
            id, client_name, payer, first_dos, last_dos,
            pending_hours, entry_date,
            DATEDIFF('day', entry_date, CURRENT_DATE) AS days_outstanding
        FROM unskilled_remit_tracker
        WHERE status != 'RESOLVED'
          AND DATEDIFF('month', entry_date, CURRENT_DATE) >= ?
        ORDER BY days_outstanding DESC
    """, [age_months]).df()


# ── Write operations (analyst only) ───────────────────────────────────────────

def save_rebill_attempt(
    conn: duckdb.DuckDBPyConnection,
    tracker_id: int,
    attempt: int,          # 1, 2, or 3
    rebill_date: date,
    rebill_hours: float,
) -> None:
    """Persist a rebill attempt date and hours for the given tracker row."""
    col_date  = f"rebill{attempt}_date"
    col_hours = f"rebill{attempt}_hours"
    conn.execute(f"""
        UPDATE unskilled_remit_tracker
        SET {col_date}  = ?,
            {col_hours} = ?,
            updated_at  = CURRENT_TIMESTAMP
        WHERE id = ?
    """, [rebill_date, rebill_hours, tracker_id])
    conn.commit()


def add_comment(
    conn: duckdb.DuckDBPyConnection,
    tracker_id: int,
    author: str,
    text: str,
) -> None:
    """Append a timestamped comment. Never overwrites existing comments."""
    conn.execute("""
        INSERT INTO unskilled_remit_comments (id, tracker_id, author, comment_text)
        VALUES (nextval('seq_unskilled_remit_comments'), ?, ?, ?)
    """, [tracker_id, author, text])
    conn.commit()


def reopen_resolved_row(conn: duckdb.DuckDBPyConnection, tracker_id: int) -> None:
    """Re-open a resolved row (e.g. clawback scenario)."""
    conn.execute("""
        UPDATE unskilled_remit_tracker
        SET status       = 'PENDING',
            payment_date = NULL,
            updated_at   = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'RESOLVED'
    """, [tracker_id])
    conn.commit()


# ── Analyst list ──────────────────────────────────────────────────────────────

ANALYST_OPTIONS: list[str] = [
    "MA",
    "MNL",
    "YN",
    "Connie",
    "Pragya",
]
