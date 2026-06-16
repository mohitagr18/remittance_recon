"""
src/db/queries.py
All validated SQL queries used by the UI and AI layers.
Every function returns a DuckDB relation or DataFrame via an open connection.
"""

from __future__ import annotations

import duckdb
import pandas as pd



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
            SUM(GREATEST(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 0)) AS pending_hrs,
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
    limit: int = 50,
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
                GREATEST(ROUND(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 1), 0) AS pending_hrs,
                ROUND(payroll_hours - billed_hours, 1) AS payroll_vs_billed,
                result_detailed,
                care_type,
                ROW_NUMBER() OVER (
                    PARTITION BY client_name_payroll
                    ORDER BY GREATEST(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 0) DESC
                ) AS rn
            FROM reconciliation
            WHERE result_simple = 'Follow up'
              AND result_detailed != 'Not Billed'
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
            result_detailed                         AS reason,
            care_type
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
            GREATEST(ROUND(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 1), 0) AS pending_hrs,
            ROUND(payroll_hours - billed_hours, 1)     AS payroll_vs_billed,
            ROUND(payroll_hours - paid_hours, 1)       AS payroll_vs_paid,
            result_simple                              AS status,
            result_detailed                            AS reason,
            is_copay_client,
            yash_comments,
            connie_comments,
            care_type
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
            SUM(payroll_hours)  AS payroll_hrs,
            SUM(billed_hours)   AS billed_hrs,
            SUM(paid_hours)     AS paid_hrs,
            SUM(GREATEST(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 0)) AS pending_hrs,
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

def client_ledger(
    conn: duckdb.DuckDBPyConnection,
    client_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    sort_asc: bool = True,
    care_type: str | None = None,
):
    """All remittance records for a given client (remittance name match).

    Aggregates multiple remittance rows per DOS into a single net row per date of service,
    showing the current state. Multiple claim lifecycle entries (original, reversal,
    re-bill, different payment batches) for the same DOS are consolidated so the user
    sees one row per DOS rather than multiple duplicate rows. Keeps care types separate.
    """
    import re
    stripped_name = re.sub(r"\s+(?:PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$", "", client_name, flags=re.IGNORECASE).strip()

    # Build the date filter clause for the outer query
    date_clauses = []
    date_params = []
    if start_date:
        date_clauses.append("COALESCE(ra.first_dos, r.week_start_date) >= ?")
        date_params.append(start_date)
    if end_date:
        date_clauses.append("COALESCE(ra.first_dos, r.week_start_date) <= ?")
        date_params.append(end_date)
    date_filter = (" AND " + " AND ".join(date_clauses)) if date_clauses else ""

    sql = f"""
        WITH rem_classified AS (
            SELECT 
                client_name_combined,
                first_dos,
                last_dos,
                payment_date,
                tcn,
                transaction_type,
                billed_hours,
                paid_hours,
                charge_amount,
                payment_amount,
                insurance,
                match_status,
                CASE 
                    -- rate-based classification
                    WHEN (billed_hours > 0 AND ABS(charge_amount / billed_hours) >= 30.0) THEN 'Skilled'
                    WHEN (paid_hours > 0 AND ABS(payment_amount / paid_hours) >= 30.0) THEN 'Skilled'
                    -- insurance-based fallback
                    WHEN (insurance LIKE '%PDN%' OR insurance LIKE '%pdn%') THEN 'Skilled'
                    ELSE 'Unskilled'
                END as care_type
            FROM remittance
            WHERE UPPER(client_name_combined) = UPPER(?)
              AND is_latest = True
        ),
        rem_daily AS (
            -- Group by client, first_dos, and payment_date to get the sum for each payment date segment.
            SELECT
                client_name_combined,
                first_dos,
                payment_date,
                SUM(billed_hours)   AS billed_hours,
                SUM(charge_amount)  AS charge_amount,
                SUM(paid_hours)     AS paid_hours,
                SUM(payment_amount) AS payment_amount,
                MAX(insurance)      AS insurance,
                MAX(match_status)   AS match_status
            FROM rem_classified
            WHERE (care_type = ? OR ? IS NULL)
            GROUP BY client_name_combined, first_dos, payment_date
        ),
        rem_agg AS (
            -- Aggregate over payment dates: select max billed/charge and sum paid.
            SELECT
                rem_daily.client_name_combined,
                rem_daily.first_dos,
                GREATEST(MAX(rem_daily.billed_hours), 0.0)    AS billed_hours,
                GREATEST(MAX(rem_daily.charge_amount), 0.0)   AS charge_amount,
                SUM(rem_daily.paid_hours)                     AS paid_hours,
                SUM(rem_daily.payment_amount)                 AS payment_amount,
                MAX(rem_daily.payment_date)                   AS payment_date,
                MAX(rem_daily.insurance)                      AS insurance,
                MAX(rem_daily.match_status)                   AS match_status,
                (SELECT rem2.tcn
                 FROM remittance rem2
                 WHERE rem2.client_name_combined = rem_daily.client_name_combined
                   AND rem2.first_dos = rem_daily.first_dos
                   AND rem2.is_latest = True
                   AND rem2.transaction_type NOT IN ('Denial/Reversal')
                 ORDER BY rem2.payment_date DESC NULLS LAST, rem2.tcn
                 LIMIT 1) AS tcn
            FROM rem_daily
            GROUP BY rem_daily.client_name_combined, rem_daily.first_dos
        )
        SELECT
            COALESCE(ra.first_dos, r.week_start_date) AS first_dos,
            COALESCE(ra.first_dos, r.week_end_date)   AS last_dos,
            ra.payment_date,
            ra.tcn,
            ra.charge_amount,
            ra.payment_amount,
            ra.billed_hours,
            ra.paid_hours,
            COALESCE(ra.insurance, r.insurance)       AS insurance,
            ra.match_status,
            r.billed_hours   AS week_billed_hours,
            r.paid_hours     AS week_paid_hours,
            r.payroll_hours  AS week_payroll_hours,
            r.result_detailed AS week_result_detailed,
            r.result_simple   AS week_result_simple
        FROM rem_agg ra
        FULL OUTER JOIN (
            SELECT * FROM reconciliation
            WHERE (care_type = ? OR ? IS NULL)
        ) r ON (
            UPPER(ra.client_name_combined) = UPPER(COALESCE(r.client_name_remittance, r.client_name_payroll))
            AND ra.first_dos BETWEEN r.week_start_date AND r.week_end_date
        )
        WHERE (
            UPPER(ra.client_name_combined) = UPPER(?)
            OR UPPER(regexp_replace(r.client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\))$', '')) = UPPER(?)
            OR UPPER(r.client_name_remittance) = UPPER(?)
        )
        {date_filter}
        {'ORDER BY COALESCE(ra.first_dos, r.week_start_date) ASC, ra.payment_date ASC' if sort_asc else 'ORDER BY ra.payment_date DESC, COALESCE(ra.first_dos, r.week_start_date) DESC'}
    """
    all_params = [
        stripped_name,
        care_type, care_type,
        care_type, care_type,
        stripped_name,
        stripped_name,
        stripped_name
    ] + date_params
    return conn.execute(sql, all_params).df()


def client_weekly_recon_with_dos(
    conn: duckdb.DuckDBPyConnection,
    client_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    care_type: str | None = None,
) -> pd.DataFrame:
    """
    Get weekly reconciliation rows for a client, joined with the minimum first_dos 
    for that client in each week from remittance, ordered by first_dos ascending.
    """
    import re
    stripped_name = re.sub(r"\s+(?:PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$", "", client_name, flags=re.IGNORECASE).strip()

    clauses = [
        """(
            UPPER(regexp_replace(r.client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\))$', '')) = UPPER(?)
            OR UPPER(r.client_name_remittance) = UPPER(?)
        )"""
    ]
    params = [stripped_name, stripped_name]

    if care_type:
        clauses.append("r.care_type = ?")
        params.append(care_type)
    if start_date:
        clauses.append("r.week_start_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("r.week_start_date <= ?")
        params.append(end_date)

    where = "WHERE " + " AND ".join(clauses)

    sql = f"""
        SELECT
            r.week_start_date,
            r.week_end_date,
            r.payroll_hours,
            r.billed_hours,
            r.paid_hours,
            GREATEST(ROUND(COALESCE(r.payroll_hours, 0) - COALESCE(r.paid_hours, 0), 2), 0) AS pending_hours,
            COALESCE(MIN(rem.first_dos), r.week_start_date) AS first_dos
        FROM reconciliation r
        LEFT JOIN remittance rem ON (
            UPPER(COALESCE(r.client_name_remittance, r.client_name_payroll)) = UPPER(rem.client_name_combined)
            AND rem.first_dos BETWEEN r.week_start_date AND r.week_end_date
            AND rem.is_latest = True
        )
        {where}
        GROUP BY r.week_start_date, r.week_end_date, r.payroll_hours, r.billed_hours, r.paid_hours
        ORDER BY first_dos ASC
    """
    return conn.execute(sql, params).df()


def client_summary(conn: duckdb.DuckDBPyConnection, client_name: str, care_type: str | None = None):
    """Aggregated YTD stats for a client (across all weeks in reconciliation)."""
    import re
    stripped_name = re.sub(r"\s+(?:PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$", "", client_name, flags=re.IGNORECASE).strip()

    care_clause = f"AND care_type = '{care_type}'" if care_type else ""

    sql = f"""
        SELECT
            COALESCE(MIN(client_name_payroll), MIN(client_name_remittance)) AS client_name_payroll,
            insurance,
            SUM(billed_hours)   AS ytd_billed_hrs,
            SUM(paid_hours)     AS ytd_paid_hrs,
            SUM(payroll_hours)  AS ytd_payroll_hrs,
            SUM(GREATEST(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 0)) AS ytd_pending_hrs,
            COUNT(*)            AS total_weeks,
            COUNT(*) FILTER (WHERE result_simple = 'Follow up') AS followup_weeks,
            ROUND(100.0 * SUM(paid_hours) / NULLIF(SUM(billed_hours), 0), 1) AS collection_rate_pct
        FROM reconciliation
        WHERE (UPPER(regexp_replace(client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\))$', '')) = UPPER(?)
           OR UPPER(client_name_remittance) = UPPER(?))
           {care_clause}
        GROUP BY insurance
    """
    return conn.execute(sql, [stripped_name, stripped_name]).df()



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
            rec.week_end_date,
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


def ingested_payroll_files_list(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return list of all ingested payroll files."""
    sql = """
        SELECT filename, row_count, week_start, week_end, ingested_at, file_hash
        FROM ingested_files
        WHERE file_type = 'payroll'
        ORDER BY ingested_at DESC
    """
    return conn.execute(sql).df()


def ingested_remittance_files_list(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return list of all ingested remittance files with min/max DOS dates."""
    sql = """
        SELECT 
            i.filename, 
            i.row_count, 
            COALESCE(i.week_start, r.min_dos) AS min_date,
            COALESCE(i.week_end, r.max_dos) AS max_date,
            i.ingested_at, 
            i.file_hash
        FROM ingested_files i
        LEFT JOIN (
            SELECT source_file, MIN(first_dos) AS min_dos, MAX(last_dos) AS max_dos
            FROM remittance
            GROUP BY source_file
        ) r ON i.filename = r.source_file
        WHERE i.file_type = 'remittance'
        ORDER BY i.ingested_at DESC
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


# ── Recent Payments & Denials ──────────────────────────────────────────────────

def recent_payments(
    conn: duckdb.DuckDBPyConnection,
    start_date: str | None = None,
    end_date: str | None = None,
    insurance: str | None = None,
    care_type: str | None = None,
    limit: int = 10,
) -> pd.DataFrame:
    """Latest payment line items matching active dashboard filters."""
    clauses = ["is_latest = True", "payment_amount > 0"]
    params = []
    
    if start_date:
        clauses.append("first_dos >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("first_dos <= ?")
        params.append(end_date)
    if insurance:
        clauses.append("insurance = ?")
        params.append(insurance)
    if care_type:
        clauses.append("""
            CASE 
                WHEN (client_name_combined LIKE '%LPN%' OR client_name_combined LIKE '%RN%' OR insurance LIKE '%PDN%') THEN 'Skilled'
                ELSE 'Unskilled'
            END = ?
        """)
        params.append(care_type)
        
    where = "WHERE " + " AND ".join(clauses)
    
    sql = f"""
        SELECT
            client_name_combined AS client,
            payment_date,
            billed_hours AS billed_hrs,
            paid_hours AS paid_hrs,
            charge_amount AS billed_amt,
            payment_amount AS paid_amt,
            first_dos
        FROM remittance
        {where}
        ORDER BY first_dos DESC, payment_date DESC
        LIMIT {limit}
    """
    return conn.execute(sql, params).df()


def recent_denials(
    conn: duckdb.DuckDBPyConnection,
    start_date: str | None = None,
    end_date: str | None = None,
    insurance: str | None = None,
    care_type: str | None = None,
    limit: int = 10,
) -> pd.DataFrame:
    """Latest denial/unpaid line items matching active dashboard filters."""
    clauses = [
        "is_latest = True",
        "(transaction_type = 'Denial/Reversal' OR (payment_amount = 0 AND charge_amount > 0))"
    ]
    params = []
    
    if start_date:
        clauses.append("first_dos >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("first_dos <= ?")
        params.append(end_date)
    if insurance:
        clauses.append("insurance = ?")
        params.append(insurance)
    if care_type:
        clauses.append("""
            CASE 
                WHEN (client_name_combined LIKE '%LPN%' OR client_name_combined LIKE '%RN%' OR insurance LIKE '%PDN%') THEN 'Skilled'
                ELSE 'Unskilled'
            END = ?
        """)
        params.append(care_type)
        
    where = "WHERE " + " AND ".join(clauses)
    
    sql = f"""
        SELECT
            client_name_combined AS client,
            payment_date,
            billed_hours AS billed_hrs,
            paid_hours AS paid_hrs,
            GREATEST(ROUND(COALESCE(billed_hours, 0) - COALESCE(paid_hours, 0), 1), 0) AS pending_hrs,
            charge_amount AS billed_amt,
            payment_amount AS paid_amt,
            ROUND(charge_amount - payment_amount, 2) AS amt_delta,
            first_dos
        FROM remittance
        {where}
        ORDER BY first_dos DESC, payment_date DESC
        LIMIT {limit}
    """
    return conn.execute(sql, params).df()


