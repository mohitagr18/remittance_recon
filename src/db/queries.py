"""
src/db/queries.py
All validated SQL queries used by the UI and AI layers.
Every function returns a DuckDB relation or DataFrame via an open connection.
"""

from __future__ import annotations

import duckdb


# ── Weekly Summary ────────────────────────────────────────────────────────────

def weekly_summary(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    insurance: str | None = None,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """KPI totals for the dashboard header cards."""
    filters = _week_insurance_filter(week_start, insurance, care_type=care_type, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            COUNT(DISTINCT COALESCE(client_name_payroll, client_name_remittance)) AS total_clients,
            SUM(payroll_hours)                                                  AS total_payroll_hrs,
            SUM(billed_hours)                                                   AS total_billed_hrs,
            SUM(paid_hours)                                                     AS total_paid_hrs,
            SUM(billed_hours - paid_hours)                                      AS pending_hrs,
            COUNT(*) FILTER (WHERE result_simple = 'Follow up')                 AS followup_count,
            ROUND(
                100.0 * SUM(paid_hours) / NULLIF(SUM(billed_hours), 0), 1
            )                                                                   AS collection_rate_pct
        FROM reconciliation
        {filters}
    """
    return conn.execute(sql).df()


# ── Follow-Up Queue ───────────────────────────────────────────────────────────

def followup_items(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    insurance: str | None = None,
    reason: str | None = None,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """All follow-up rows with detail reason, sorted by payroll_vs_billed desc."""
    clauses = ["result_simple = 'Follow up'"]
    if week_start:
        clauses.append(f"week_start_date = '{week_start}'")
    else:
        if start_date:
            clauses.append(f"week_start_date >= '{start_date}'")
        if end_date:
            clauses.append(f"week_start_date <= '{end_date}'")
    if insurance:
        clauses.append(f"insurance = '{insurance}'")
    if reason:
        clauses.append(f"result_detailed = '{reason}'")
    if care_type:
        clauses.append(f"care_type = '{care_type}'")
    where = "WHERE " + " AND ".join(clauses)
    sql = f"""
        SELECT
            id,
            week_start_date,
            week_end_date,
            insurance,
            client_name_payroll,
            client_name_remittance,
            payroll_hours,
            billed_hours,
            paid_hours,
            payroll_vs_billed,
            billing_vs_paid,
            payroll_vs_paid,
            result_simple,
            result_detailed,
            analyst_override,
            yash_comments,
            connie_comments
        FROM reconciliation
        {where}
        ORDER BY ABS(payroll_vs_billed) DESC, client_name_payroll
    """
    return conn.execute(sql).df()


def top_followup_clients(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    insurance: str | None = None,
    limit: int = 15,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Deduplicated follow-up clients for the COO dashboard.
    One row per client (worst-case week chosen by max pending hours).
    Includes date range and pending hours. Sorted by pending_hrs descending.
    """
    if week_start:
        date_clause = f"AND week_start_date = '{week_start}'"
    else:
        date_clause = ""
        if start_date:
            date_clause += f" AND week_start_date >= '{start_date}'"
        if end_date:
            date_clause += f" AND week_start_date <= '{end_date}'"
            
    ins_clause  = f"AND insurance = '{insurance}'"        if insurance  else ""
    care_clause = f"AND care_type = '{care_type}'"        if care_type  else ""
    sql = f"""
        WITH ranked AS (
            SELECT
                insurance,
                client_name_payroll,
                week_start_date,
                week_end_date,
                payroll_hours,
                billed_hours,
                paid_hours,
                ROUND(billed_hours - paid_hours, 1)    AS pending_hrs,
                ROUND(payroll_hours - billed_hours, 1) AS payroll_vs_billed,
                result_detailed,
                ROW_NUMBER() OVER (
                    PARTITION BY client_name_payroll
                    ORDER BY (billed_hours - paid_hours) DESC
                ) AS rn
            FROM reconciliation
            WHERE result_simple = 'Follow up'
              {date_clause}
              {ins_clause}
              {care_clause}
        )
        SELECT
            insurance,
            client_name_payroll                     AS client,
            week_start_date                         AS week_start,
            week_end_date                           AS week_end,
            payroll_hours,
            billed_hours,
            paid_hours,
            pending_hrs,
            payroll_vs_billed,
            result_detailed                         AS reason
        FROM ranked
        WHERE rn = 1
        ORDER BY pending_hrs DESC
        LIMIT {limit}
    """
    return conn.execute(sql).df()


def weekly_recon_detail(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    insurance: str | None = None,
    follow_up_only: bool = False,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Excel-style weekly reconciliation view — one row per client.
    Columns: Insurance | Client | Week | Payroll Hrs | Billed Hrs |
             Paid Hrs | Pending Hrs | Status | Reason
    Sorted by pending_hrs descending (largest shortfall first).
    """
    clauses = []
    if week_start:
        clauses.append(f"week_start_date = '{week_start}'")
    else:
        if start_date:
            clauses.append(f"week_start_date >= '{start_date}'")
        if end_date:
            clauses.append(f"week_start_date <= '{end_date}'")
    if insurance:
        clauses.append(f"insurance = '{insurance}'")
    if follow_up_only:
        clauses.append("result_simple = 'Follow up'")
    if care_type:
        clauses.append(f"care_type = '{care_type}'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT
            insurance,
            client_name_payroll                        AS client,
            week_start_date                            AS week_start,
            week_end_date                              AS week_end,
            payroll_hours,
            billed_hours,
            paid_hours,
            ROUND(billed_hours - paid_hours, 1)        AS pending_hrs,
            ROUND(payroll_hours - billed_hours, 1)     AS payroll_vs_billed,
            ROUND(payroll_hours - paid_hours, 1)       AS payroll_vs_paid,
            result_simple                              AS status,
            result_detailed                            AS reason,
            is_copay_client,
            yash_comments,
            connie_comments
        FROM reconciliation
        {where}
        ORDER BY pending_hrs DESC, ABS(payroll_vs_billed) DESC
    """
    return conn.execute(sql).df()

# ── All Reconciliation Rows ───────────────────────────────────────────────────

def all_reconciliation(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    insurance: str | None = None,
    follow_up_only: bool = False,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    clauses = []
    if week_start:
        clauses.append(f"week_start_date = '{week_start}'")
    else:
        if start_date:
            clauses.append(f"week_start_date >= '{start_date}'")
        if end_date:
            clauses.append(f"week_start_date <= '{end_date}'")
    if insurance:
        clauses.append(f"insurance = '{insurance}'")
    if follow_up_only:
        clauses.append("result_simple = 'Follow up'")
    if care_type:
        clauses.append(f"care_type = '{care_type}'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT
            id,
            week_start_date,
            week_end_date,
            insurance,
            client_name_payroll,
            client_name_remittance,
            payroll_hours,
            billed_hours,
            paid_hours,
            payroll_vs_billed,
            billing_vs_paid,
            payroll_vs_paid,
            result_simple,
            result_detailed,
            analyst_override,
            is_copay_client,
            match_status,
            yash_comments,
            connie_comments
        FROM reconciliation
        {where}
        ORDER BY insurance, client_name_payroll
    """
    return conn.execute(sql).df()


# ── Follow-Up Reason Breakdown (donut chart) ──────────────────────────────────

def followup_reason_breakdown(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    insurance: str | None = None,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    filters = _week_insurance_filter(week_start, insurance, care_type=care_type, start_date=start_date, end_date=end_date, prefix="AND")
    sql = f"""
        SELECT
            COALESCE(result_detailed, 'Unclassified') AS reason,
            COUNT(*) AS count
        FROM reconciliation
        WHERE result_simple = 'Follow up'
        {filters}
        GROUP BY reason
        ORDER BY count DESC
    """
    return conn.execute(sql).df()


# ── Payer Collection Rates ────────────────────────────────────────────────────

def payer_collection_rates(
    conn: duckdb.DuckDBPyConnection,
    week_start: str | None = None,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    if week_start:
        week_filter = f"AND week_start_date = '{week_start}'"
    else:
        week_filter = ""
        if start_date:
            week_filter += f" AND week_start_date >= '{start_date}'"
        if end_date:
            week_filter += f" AND week_start_date <= '{end_date}'"
            
    care_filter = f"AND care_type = '{care_type}'" if care_type else ""
    sql = f"""
        SELECT
            insurance,
            SUM(billed_hours)                                           AS billed_hrs,
            SUM(paid_hours)                                             AS paid_hrs,
            ROUND(100.0 * SUM(paid_hours) / NULLIF(SUM(billed_hours), 0), 1) AS collection_rate_pct,
            COUNT(*) FILTER (WHERE result_simple = 'Follow up')         AS followup_count
        FROM reconciliation
        WHERE insurance IS NOT NULL
        {week_filter}
        {care_filter}
        GROUP BY insurance
        ORDER BY collection_rate_pct DESC
    """
    return conn.execute(sql).df()


# ── 12-Week Rolling Trend ─────────────────────────────────────────────────────

def rolling_trend(
    conn: duckdb.DuckDBPyConnection,
    weeks: int = 12,
    insurance: str | None = None,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    ins_filter = f"AND insurance = '{insurance}'" if insurance else ""
    care_filter = f"AND care_type = '{care_type}'" if care_type else ""
    
    date_filter = ""
    if start_date:
        date_filter += f" AND week_start_date >= '{start_date}'"
    if end_date:
        date_filter += f" AND week_start_date <= '{end_date}'"
        
    sql = f"""
        SELECT
            week_start_date,
            SUM(billed_hours)   AS billed_hrs,
            SUM(paid_hours)     AS paid_hrs,
            SUM(billed_hours - paid_hours) AS pending_hrs,
            COUNT(*) FILTER (WHERE result_simple = 'Follow up') AS followup_count
        FROM reconciliation
        WHERE 1=1 {ins_filter} {care_filter} {date_filter}
        GROUP BY week_start_date
        ORDER BY week_start_date DESC
        LIMIT {weeks}
    """
    df = conn.execute(sql).df()
    return df.sort_values("week_start_date")


# ── Client Ledger ─────────────────────────────────────────────────────────────

def client_ledger(conn: duckdb.DuckDBPyConnection, client_name: str):
    """All remittance records for a given client (remittance name match)."""
    sql = """
        SELECT
            payment_date,
            tcn,
            first_dos,
            last_dos,
            transaction_type,
            claim_number,
            charge_amount,
            payment_amount,
            billed_hours,
            paid_hours,
            insurance,
            match_status
        FROM remittance
        WHERE UPPER(client_name_combined) = UPPER(?)
           OR UPPER(client_first_name || ' ' || client_last_name) = UPPER(?)
        ORDER BY payment_date DESC, first_dos DESC
    """
    return conn.execute(sql, [client_name, client_name]).df()


def client_summary(conn: duckdb.DuckDBPyConnection, client_name: str):
    """Aggregated YTD stats for a client (across all weeks in reconciliation)."""
    sql = """
        SELECT
            client_name_payroll,
            insurance,
            SUM(billed_hours)   AS ytd_billed_hrs,
            SUM(paid_hours)     AS ytd_paid_hrs,
            SUM(payroll_hours)  AS ytd_payroll_hrs,
            COUNT(*)            AS total_weeks,
            COUNT(*) FILTER (WHERE result_simple = 'Follow up') AS followup_weeks,
            ROUND(100.0 * SUM(paid_hours) / NULLIF(SUM(billed_hours), 0), 1) AS collection_rate_pct
        FROM reconciliation
        WHERE UPPER(client_name_payroll) LIKE UPPER(?)
        GROUP BY client_name_payroll, insurance
    """
    return conn.execute(sql, [f"%{client_name}%"]).df()


# ── Distinct Weeks ────────────────────────────────────────────────────────────

def available_weeks(conn: duckdb.DuckDBPyConnection):
    sql = """
        SELECT DISTINCT week_start_date, week_end_date
        FROM reconciliation
        ORDER BY week_start_date DESC
    """
    return conn.execute(sql).df()


def available_insurances(conn: duckdb.DuckDBPyConnection):
    sql = """
        SELECT DISTINCT insurance
        FROM reconciliation
        WHERE insurance IS NOT NULL
        ORDER BY insurance
    """
    return conn.execute(sql).df()["insurance"].tolist()


def available_result_details(conn: duckdb.DuckDBPyConnection):
    sql = """
        SELECT DISTINCT result_detailed
        FROM reconciliation
        WHERE result_detailed IS NOT NULL
        ORDER BY result_detailed
    """
    return conn.execute(sql).df()["result_detailed"].tolist()


# ── Client List ───────────────────────────────────────────────────────────────

def all_clients(conn: duckdb.DuckDBPyConnection):
    sql = """
        SELECT DISTINCT client_name_payroll
        FROM reconciliation
        WHERE client_name_payroll IS NOT NULL
        ORDER BY client_name_payroll
    """
    return conn.execute(sql).df()["client_name_payroll"].tolist()


# ── Name Match Manager ────────────────────────────────────────────────────────

def get_name_match_table(conn: duckdb.DuckDBPyConnection):
    return conn.execute("SELECT * FROM name_match ORDER BY payroll_name").df()


def upsert_name_match(conn: duckdb.DuckDBPyConnection, payroll_name: str, remittance_name: str | None):
    existing = conn.execute(
        "SELECT id FROM name_match WHERE UPPER(payroll_name) = UPPER(?)", [payroll_name]
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE name_match SET remittance_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [remittance_name, existing[0]],
        )
    else:
        conn.execute(
            "INSERT INTO name_match (id, payroll_name, remittance_name) VALUES (nextval('seq_name_match'), ?, ?)",
            [payroll_name, remittance_name],
        )
    conn.commit()


# ── Copay List ────────────────────────────────────────────────────────────────

def get_copay_table(conn: duckdb.DuckDBPyConnection):
    return conn.execute("SELECT * FROM copay_clients ORDER BY client_name").df()


# ── Rebill Tracker ────────────────────────────────────────────────────────────

def get_rebill_items(conn: duckdb.DuckDBPyConnection):
    sql = """
        SELECT
            r.id,
            rec.insurance,
            rec.client_name_payroll,
            rec.week_start_date,
            r.tcn,
            r.denial_code,
            r.rebill_date,
            r.status,
            r.notes,
            r.created_at
        FROM rebill_tracker r
        JOIN reconciliation rec ON r.reconciliation_id = rec.id
        ORDER BY r.created_at DESC
    """
    return conn.execute(sql).df()


def add_rebill_item(
    conn: duckdb.DuckDBPyConnection,
    reconciliation_id: int,
    tcn: str | None = None,
    denial_code: str | None = None,
    notes: str | None = None,
):
    conn.execute(
        """INSERT INTO rebill_tracker (id, reconciliation_id, tcn, denial_code, notes)
           VALUES (nextval('seq_rebill_tracker'), ?, ?, ?, ?)""",
        [reconciliation_id, tcn, denial_code, notes],
    )
    conn.commit()


def mark_reviewed(conn: duckdb.DuckDBPyConnection, reconciliation_id: int, performed_by: str = "analyst"):
    conn.execute(
        """INSERT INTO review_actions (id, reconciliation_id, action, performed_by)
           VALUES (nextval('seq_review_actions'), ?, 'MARK_REVIEWED', ?)""",
        [reconciliation_id, performed_by],
    )
    conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def ingested_files_list(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return list of all ingested files."""
    sql = """
        SELECT filename, file_type, row_count, week_start, week_end, ingested_at, file_hash
        FROM ingested_files
        ORDER BY ingested_at DESC
    """
    return conn.execute(sql).df()


def _week_insurance_filter(
    week_start: str | None,
    insurance: str | None,
    care_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    prefix: str = "WHERE",
) -> str:
    clauses = []
    if week_start:
        clauses.append(f"week_start_date = '{week_start}'")
    else:
        if start_date:
            clauses.append(f"week_start_date >= '{start_date}'")
        if end_date:
            clauses.append(f"week_start_date <= '{end_date}'")
            
    if insurance:
        clauses.append(f"insurance = '{insurance}'")
    if care_type:
        clauses.append(f"care_type = '{care_type}'")
    if not clauses:
        return ""
    return prefix + " " + " AND ".join(clauses)
