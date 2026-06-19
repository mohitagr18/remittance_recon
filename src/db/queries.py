"""
src/db/queries.py
All validated SQL queries used by the UI and AI layers.
Every function returns a DuckDB relation or DataFrame via an open connection.
"""

from __future__ import annotations

import duckdb
import pandas as pd


# ── Copay Monthly Status ───────────────────────────────────────────────────────

def copay_monthly_status(
    conn: duckdb.DuckDBPyConnection,
    year: int | None = None,
    month: int | None = None,
) -> pd.DataFrame:
    """
    Monthly copay reconciliation view.

    For each copay client × month, sums pending dollars across all weeks
    and compares to the client's monthly copay_amount.

    Returns columns:
        client_name, insurance, copay_amount, month_label,
        total_billed_dollars, total_paid_dollars, pending_dollars,
        copay_status, copay_note
    where copay_status ∈ {'Good', 'Follow up'}
    and   copay_note   ∈ {'Copay', 'Exceeds Copay', 'Partial Copay', None}
    """
    month_filter = ""
    if year:
        month_filter += f" AND DATE_PART('year', r.week_start_date) = {year}"
    if month:
        month_filter += f" AND DATE_PART('month', r.week_start_date) = {month}"

    sql = f"""
        WITH copay_clients_active AS (
            SELECT client_name, copay_amount, insurance, effective_from, effective_to
            FROM copay_clients
            WHERE is_active = TRUE AND copay_amount IS NOT NULL
        ),
        recon_monthly AS (
            SELECT
                regexp_replace(r.client_name_payroll, '(?i)\s+(Live-?[Ii]n|PCA|LPN|RN|CNA|HHA|MA|NP|PA|CHHA)$', '') AS client_name_payroll,
                r.insurance,
                DATE_PART('year', r.week_start_date)::INT  AS yr,
                DATE_PART('month', r.week_start_date)::INT AS mo,
                SUM(r.billed_hours  * COALESCE(rem.charge_amount  / NULLIF(rem.billed_hours, 0), 0)) AS total_billed_dollars,
                SUM(r.paid_hours    * COALESCE(rem.payment_amount / NULLIF(rem.paid_hours,   0), 0)) AS total_paid_dollars
            FROM reconciliation r
            LEFT JOIN (
                SELECT
                    client_name_combined,
                    SUM(charge_amount)  AS charge_amount,
                    SUM(payment_amount) AS payment_amount,
                    MAX(billed_hours)   AS billed_hours,
                    SUM(paid_hours)     AS paid_hours,
                    first_dos
                FROM remittance
                WHERE is_latest = TRUE
                GROUP BY client_name_combined, first_dos
            ) rem
              ON UPPER(r.client_name_remittance) = UPPER(rem.client_name_combined)
             AND rem.first_dos BETWEEN r.week_start_date AND r.week_end_date
            WHERE UPPER(regexp_replace(r.client_name_payroll, '(?i)\s+(Live-?[Ii]n|PCA|LPN|RN|CNA|HHA|MA|NP|PA|CHHA)$', '')) IN (SELECT UPPER(client_name) FROM copay_clients_active)
            {month_filter}
            GROUP BY regexp_replace(r.client_name_payroll, '(?i)\s+(Live-?[Ii]n|PCA|LPN|RN|CNA|HHA|MA|NP|PA|CHHA)$', ''), r.insurance, yr, mo
        ),
        monthly_pending AS (
            SELECT
                rm.client_name_payroll AS client_name,
                rm.insurance,
                cc.copay_amount,
                cc.effective_from,
                cc.effective_to,
                rm.yr,
                rm.mo,
                STRFTIME(MAKE_DATE(rm.yr, rm.mo, 1), '%b %Y') AS month_label,
                ROUND(COALESCE(rm.total_billed_dollars, 0), 2) AS total_billed_dollars,
                ROUND(COALESCE(rm.total_paid_dollars,   0), 2) AS total_paid_dollars,
                ROUND(COALESCE(rm.total_billed_dollars, 0) - COALESCE(rm.total_paid_dollars, 0), 2) AS pending_dollars
            FROM recon_monthly rm
            JOIN copay_clients_active cc
              ON UPPER(cc.client_name) = UPPER(rm.client_name_payroll)
        )
        SELECT
            client_name,
            insurance,
            copay_amount,
            month_label,
            yr,
            mo,
            total_billed_dollars,
            total_paid_dollars,
            pending_dollars,
            CASE
                WHEN ABS(pending_dollars) <= 1.00
                    THEN 'Good'
                WHEN ABS(pending_dollars - copay_amount) <= 1.00
                    THEN 'Good'
                WHEN pending_dollars > copay_amount + 1.00
                    THEN 'Follow up'
                WHEN pending_dollars > 1.00 AND pending_dollars < copay_amount - 1.00
                    THEN 'Follow up'
                ELSE 'Good'
            END AS copay_status,
            CASE
                WHEN ABS(pending_dollars) <= 1.00
                    THEN NULL
                WHEN ABS(pending_dollars - copay_amount) <= 1.00
                    THEN 'Copay'
                WHEN pending_dollars > copay_amount + 1.00
                    THEN 'Exceeds Copay'
                WHEN pending_dollars > 1.00 AND pending_dollars < copay_amount - 1.00
                    THEN 'Partial Copay'
                ELSE NULL
            END AS copay_note
        FROM monthly_pending
        ORDER BY client_name, yr, mo
    """
    return conn.execute(sql).df()


def copay_management(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """All copay clients with their current amounts for the management UI."""
    return conn.execute("""
        SELECT
            id,
            client_name,
            insurance,
            copay_amount,
            effective_from,
            effective_to,
            is_active,
            updated_at
        FROM copay_clients
        ORDER BY client_name
    """).df()


def upsert_copay_client(
    conn: duckdb.DuckDBPyConnection,
    client_id: int,
    copay_amount: float,
    effective_from: str | None,
    effective_to: str | None,
    is_active: bool = True,
) -> None:
    """Update a copay client's amount and date range."""
    conn.execute("""
        UPDATE copay_clients
        SET copay_amount   = ?,
            effective_from = CAST(? AS DATE),
            effective_to   = CAST(? AS DATE),
            is_active      = ?,
            updated_at     = CURRENT_TIMESTAMP
        WHERE id = ?
    """, [copay_amount, effective_from, effective_to, is_active, client_id])




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
        date_clauses.append("COALESCE(ra.first_dos, r.week_end_date) <= ?")
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
            WHERE (
                UPPER(client_name_combined) = UPPER(?)
                OR UPPER(client_name_combined) IN (
                    SELECT DISTINCT UPPER(client_name_remittance)
                    FROM reconciliation
                    WHERE UPPER(regexp_replace(client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\)|Live-?[Ii]n|LIVE-?IN)$', '')) = UPPER(?)
                       OR UPPER(client_name_remittance) = UPPER(?)
                )
            )
              AND is_latest = True
        ),
        rem_daily AS (
            -- Group by client, first_dos, and payment_date to get the sum for each payment date segment.
            SELECT
                client_name_combined,
                first_dos,
                payment_date,
                MAX(billed_hours)   AS billed_hours,
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
            -- One row per (DOS, payment_date) so the ledger/drilldown shows all payments.
            -- Billed hours: take MAX across any split claims on the same day.
            -- Paid hours: SUM across all partial payments on the same day.
            SELECT
                rem_daily.client_name_combined,
                rem_daily.first_dos,
                rem_daily.payment_date,
                GREATEST(MAX(rem_daily.billed_hours), 0.0)    AS billed_hours,
                GREATEST(MAX(rem_daily.charge_amount), 0.0)   AS charge_amount,
                SUM(rem_daily.paid_hours)                     AS paid_hours,
                SUM(rem_daily.payment_amount)                 AS payment_amount,
                MAX(rem_daily.insurance)                      AS insurance,
                MAX(rem_daily.match_status)                   AS match_status,
                (SELECT rem2.tcn
                 FROM remittance rem2
                 WHERE rem2.client_name_combined = rem_daily.client_name_combined
                   AND rem2.first_dos = rem_daily.first_dos
                   AND rem2.payment_date = rem_daily.payment_date
                   AND rem2.is_latest = True
                   AND rem2.transaction_type NOT IN ('Denial/Reversal')
                 LIMIT 1) AS tcn
            FROM rem_daily
            GROUP BY rem_daily.client_name_combined, rem_daily.first_dos, rem_daily.payment_date
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
            OR UPPER(regexp_replace(r.client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\)|Live-?[Ii]n|LIVE-?IN)$', '')) = UPPER(?)
            OR UPPER(r.client_name_remittance) = UPPER(?)
        )
        {date_filter}
        {'ORDER BY COALESCE(ra.first_dos, r.week_start_date) ASC, ra.payment_date ASC' if sort_asc else 'ORDER BY ra.payment_date DESC, COALESCE(ra.first_dos, r.week_start_date) DESC'}
    """
    all_params = [
        stripped_name, stripped_name, stripped_name,
        care_type, care_type,
        care_type, care_type,
        stripped_name,
        stripped_name,
        stripped_name
    ] + date_params
    return conn.execute(sql, all_params).df()


def client_raw_remittance_claims(
    conn: duckdb.DuckDBPyConnection,
    client_name: str,
    week_start: str,
    week_end: str,
    care_type: str | None = None,
) -> pd.DataFrame:
    """Return raw, un-aggregated remittance records for a client and DOS week range.

    Unlike client_ledger (which aggregates via rem_daily/rem_agg and filters by
    is_latest), this returns every individual remittance row exactly as stored,
    so the Daily Claims Detail table shows the same records the user sees in the
    master remittance Excel.

    No is_latest filtering is applied — all records for the client and date range
    are returned.
    """
    import re
    stripped_name = re.sub(
        r"(?i)\s+(PCA|LPN|RN|CNA|HHA|MA|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\)|Live-?[Ii]n|LIVE-?IN)$",
        "", client_name.strip()
    )

    sql = """
        SELECT
            r.first_dos,
            r.last_dos,
            r.payment_date,
            r.tcn,
            r.batch,
            r.transaction_type,
            r.match_status,
            r.billed_hours,
            r.paid_hours,
            r.charge_amount,
            r.payment_amount,
            r.insurance
        FROM remittance r
        WHERE (
            UPPER(r.client_name_combined) = UPPER(?)
            OR UPPER(r.client_name_combined) IN (
                SELECT DISTINCT UPPER(client_name_remittance)
                FROM reconciliation
                WHERE UPPER(regexp_replace(client_name_payroll,
                      '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\)|Live-?[Ii]n|LIVE-?IN)$', ''))
                      = UPPER(?)
                   OR UPPER(client_name_remittance) = UPPER(?)
            )
        )
        AND r.first_dos >= ?
        AND r.first_dos <= ?
        ORDER BY r.first_dos, r.payment_date, r.batch
    """
    params = [stripped_name, stripped_name, stripped_name, week_start, week_end]
    return conn.execute(sql, params).df()

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
            UPPER(regexp_replace(r.client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\)|Live-?[Ii]n|LIVE-?IN)$', '')) = UPPER(?)
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
            MIN(client_name_remittance) AS client_name_remittance,
            insurance,
            SUM(billed_hours)   AS ytd_billed_hrs,
            SUM(paid_hours)     AS ytd_paid_hrs,
            SUM(payroll_hours)  AS ytd_payroll_hrs,
            SUM(GREATEST(COALESCE(payroll_hours, 0) - COALESCE(paid_hours, 0), 0)) AS ytd_pending_hrs,
            COUNT(*)            AS total_weeks,
            COUNT(*) FILTER (WHERE result_simple = 'Follow up') AS followup_weeks,
            ROUND(100.0 * SUM(paid_hours) / NULLIF(SUM(billed_hours), 0), 1) AS collection_rate_pct
        FROM reconciliation
        WHERE (UPPER(regexp_replace(client_name_payroll, '(?i)\\s+(PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\\(LPN\\)|\\(RN\\)|\\(PCA\\)|Live-?[Ii]n|LIVE-?IN)$', '')) = UPPER(?)
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




# ── Skilled Tracker Queries ────────────────────────────────────────────────────

def get_tracker_clients(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """All active (display_name, bill_code) pairs ordered by display_name."""
    return conn.execute("""
        SELECT id, display_name, bill_code, service_type, remittance_name, is_active
        FROM skilled_tracker_clients
        WHERE is_active = TRUE
        ORDER BY display_name, bill_code
    """).df()


def get_tracker_week_data(
    conn: duckdb.DuckDBPyConnection,
    week_start: str,
    week_end: str,
) -> pd.DataFrame:
    """
    Returns one row per active (display_name, bill_code) for the given week.
    Aggregates remittance rows whose DOS falls within [week_start, week_end].
    Also pulls payroll hours from reconciliation for the same week.
    """
    return conn.execute("""
        WITH clients AS (
            SELECT display_name, bill_code, service_type, remittance_name
            FROM skilled_tracker_clients
            WHERE is_active = TRUE
               OR (deactivated_from IS NOT NULL AND deactivated_from > CAST(? AS DATE))
        ),
        rem AS (
            SELECT
                c.display_name,
                c.bill_code,
                SUM(r.charge_amount)   AS billed_amt,
                SUM(r.payment_amount)  AS paid_amt,
                SUM(r.billed_hours)    AS billed_hrs,
                SUM(r.paid_hours)      AS paid_hrs,
                COUNT(r.id)            AS txn_count
            FROM clients c
            JOIN remittance r
                ON r.client_name_combined = c.remittance_name
               AND r.first_dos BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
               AND r.is_latest = TRUE
            GROUP BY c.display_name, c.bill_code
        ),
        recon AS (
            SELECT
                c.display_name,
                c.bill_code,
                SUM(rc.payroll_hours) AS payroll_hrs
            FROM clients c
            JOIN reconciliation rc
                ON rc.client_name_payroll = c.display_name
               AND rc.week_start_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            GROUP BY c.display_name, c.bill_code
        )
        SELECT
            cl.display_name,
            cl.bill_code,
            cl.service_type,
            COALESCE(recon.payroll_hrs, 0)                              AS payroll_hrs,
            COALESCE(rem.billed_hrs, 0)                                 AS units_billed,
            COALESCE(rem.billed_amt, 0)                                 AS billed_amt,
            COALESCE(rem.paid_amt, 0)                                   AS paid_amt,
            COALESCE(rem.billed_amt, 0) - COALESCE(rem.paid_amt, 0)    AS pending_amt,
            CASE
                WHEN COALESCE(rem.billed_amt, 0) = 0 THEN 'No Claims'
                WHEN COALESCE(rem.paid_amt, 0) >= COALESCE(rem.billed_amt, 0) THEN 'Paid in Full'
                WHEN COALESCE(rem.paid_amt, 0) > 0 THEN 'Partial'
                ELSE 'Unpaid'
            END AS status,
            COALESCE(rem.txn_count, 0) AS txn_count
        FROM clients cl
        LEFT JOIN rem   ON rem.display_name  = cl.display_name AND rem.bill_code  = cl.bill_code
        LEFT JOIN recon ON recon.display_name = cl.display_name AND recon.bill_code = cl.bill_code
        ORDER BY cl.display_name, cl.bill_code
    """, [week_start, week_start, week_end, week_start, week_end]).df()


def get_tracker_ytd(conn: duckdb.DuckDBPyConnection, year: int = 2026) -> pd.DataFrame:
    """YTD summary per (display_name, bill_code) with monthly paid breakdown."""
    return conn.execute("""
        WITH clients AS (
            SELECT display_name, bill_code, service_type, remittance_name
            FROM skilled_tracker_clients WHERE is_active = TRUE
        ),
        monthly AS (
            SELECT
                c.display_name, c.bill_code,
                DATE_PART('month', r.first_dos) AS month_num,
                SUM(r.charge_amount)  AS billed_amt,
                SUM(r.payment_amount) AS paid_amt,
                SUM(r.billed_hours)   AS billed_hrs
            FROM clients c
            JOIN remittance r
                ON r.client_name_combined = c.remittance_name
               AND DATE_PART('year', r.first_dos) = ?
               AND r.is_latest = TRUE
            GROUP BY c.display_name, c.bill_code, DATE_PART('month', r.first_dos)
        )
        SELECT
            c.display_name,
            c.bill_code,
            c.service_type,
            COALESCE(SUM(m.billed_hrs), 0)  AS total_hrs,
            COALESCE(SUM(m.billed_amt), 0)  AS total_billed,
            COALESCE(SUM(m.paid_amt), 0)    AS total_paid,
            COALESCE(SUM(m.billed_amt), 0) - COALESCE(SUM(m.paid_amt), 0) AS total_pending,
            COALESCE(SUM(CASE WHEN m.month_num = 1  THEN m.paid_amt ELSE 0 END), 0) AS jan,
            COALESCE(SUM(CASE WHEN m.month_num = 2  THEN m.paid_amt ELSE 0 END), 0) AS feb,
            COALESCE(SUM(CASE WHEN m.month_num = 3  THEN m.paid_amt ELSE 0 END), 0) AS mar,
            COALESCE(SUM(CASE WHEN m.month_num = 4  THEN m.paid_amt ELSE 0 END), 0) AS apr,
            COALESCE(SUM(CASE WHEN m.month_num = 5  THEN m.paid_amt ELSE 0 END), 0) AS may,
            COALESCE(SUM(CASE WHEN m.month_num = 6  THEN m.paid_amt ELSE 0 END), 0) AS jun,
            COALESCE(SUM(CASE WHEN m.month_num = 7  THEN m.paid_amt ELSE 0 END), 0) AS jul,
            COALESCE(SUM(CASE WHEN m.month_num = 8  THEN m.paid_amt ELSE 0 END), 0) AS aug,
            COALESCE(SUM(CASE WHEN m.month_num = 9  THEN m.paid_amt ELSE 0 END), 0) AS sep,
            COALESCE(SUM(CASE WHEN m.month_num = 10 THEN m.paid_amt ELSE 0 END), 0) AS oct,
            COALESCE(SUM(CASE WHEN m.month_num = 11 THEN m.paid_amt ELSE 0 END), 0) AS nov,
            COALESCE(SUM(CASE WHEN m.month_num = 12 THEN m.paid_amt ELSE 0 END), 0) AS dec_
        FROM clients c
        LEFT JOIN monthly m ON m.display_name = c.display_name AND m.bill_code = c.bill_code
        GROUP BY c.display_name, c.bill_code, c.service_type
        ORDER BY total_billed DESC
    """, [year]).df()



def get_tracker_heatmap(conn: duckdb.DuckDBPyConnection, year: int = 2026) -> pd.DataFrame:
    """Per (client, month) collection rate % for heatmap. Returns wide dataframe."""
    return conn.execute("""
        WITH clients AS (
            SELECT display_name, bill_code, remittance_name
            FROM skilled_tracker_clients WHERE is_active = TRUE
        ),
        monthly AS (
            SELECT
                c.display_name,
                c.bill_code,
                DATE_PART('month', r.first_dos) AS month_num,
                SUM(r.charge_amount)  AS billed_amt,
                SUM(r.payment_amount) AS paid_amt
            FROM clients c
            JOIN remittance r
                ON r.client_name_combined = c.remittance_name
               AND DATE_PART('year', r.first_dos) = ?
               AND r.is_latest = TRUE
            GROUP BY c.display_name, c.bill_code, DATE_PART('month', r.first_dos)
        )
        SELECT
            c.display_name || ' ('  || c.bill_code || ')' AS client_label,
            COALESCE(SUM(CASE WHEN m.month_num = 1  THEN m.billed_amt ELSE 0 END), 0) AS jan_b,
            COALESCE(SUM(CASE WHEN m.month_num = 1  THEN m.paid_amt   ELSE 0 END), 0) AS jan_p,
            COALESCE(SUM(CASE WHEN m.month_num = 2  THEN m.billed_amt ELSE 0 END), 0) AS feb_b,
            COALESCE(SUM(CASE WHEN m.month_num = 2  THEN m.paid_amt   ELSE 0 END), 0) AS feb_p,
            COALESCE(SUM(CASE WHEN m.month_num = 3  THEN m.billed_amt ELSE 0 END), 0) AS mar_b,
            COALESCE(SUM(CASE WHEN m.month_num = 3  THEN m.paid_amt   ELSE 0 END), 0) AS mar_p,
            COALESCE(SUM(CASE WHEN m.month_num = 4  THEN m.billed_amt ELSE 0 END), 0) AS apr_b,
            COALESCE(SUM(CASE WHEN m.month_num = 4  THEN m.paid_amt   ELSE 0 END), 0) AS apr_p,
            COALESCE(SUM(CASE WHEN m.month_num = 5  THEN m.billed_amt ELSE 0 END), 0) AS may_b,
            COALESCE(SUM(CASE WHEN m.month_num = 5  THEN m.paid_amt   ELSE 0 END), 0) AS may_p,
            COALESCE(SUM(CASE WHEN m.month_num = 6  THEN m.billed_amt ELSE 0 END), 0) AS jun_b,
            COALESCE(SUM(CASE WHEN m.month_num = 6  THEN m.paid_amt   ELSE 0 END), 0) AS jun_p,
            COALESCE(SUM(CASE WHEN m.month_num = 7  THEN m.billed_amt ELSE 0 END), 0) AS jul_b,
            COALESCE(SUM(CASE WHEN m.month_num = 7  THEN m.paid_amt   ELSE 0 END), 0) AS jul_p,
            COALESCE(SUM(CASE WHEN m.month_num = 8  THEN m.billed_amt ELSE 0 END), 0) AS aug_b,
            COALESCE(SUM(CASE WHEN m.month_num = 8  THEN m.paid_amt   ELSE 0 END), 0) AS aug_p,
            COALESCE(SUM(CASE WHEN m.month_num = 9  THEN m.billed_amt ELSE 0 END), 0) AS sep_b,
            COALESCE(SUM(CASE WHEN m.month_num = 9  THEN m.paid_amt   ELSE 0 END), 0) AS sep_p,
            COALESCE(SUM(CASE WHEN m.month_num = 10 THEN m.billed_amt ELSE 0 END), 0) AS oct_b,
            COALESCE(SUM(CASE WHEN m.month_num = 10 THEN m.paid_amt   ELSE 0 END), 0) AS oct_p,
            COALESCE(SUM(CASE WHEN m.month_num = 11 THEN m.billed_amt ELSE 0 END), 0) AS nov_b,
            COALESCE(SUM(CASE WHEN m.month_num = 11 THEN m.paid_amt   ELSE 0 END), 0) AS nov_p,
            COALESCE(SUM(CASE WHEN m.month_num = 12 THEN m.billed_amt ELSE 0 END), 0) AS dec_b,
            COALESCE(SUM(CASE WHEN m.month_num = 12 THEN m.paid_amt   ELSE 0 END), 0) AS dec_p
        FROM clients c
        LEFT JOIN monthly m ON m.display_name = c.display_name AND m.bill_code = c.bill_code
        GROUP BY c.display_name, c.bill_code
        ORDER BY c.display_name
    """, [year]).df()

def get_tracker_comments(
    conn: duckdb.DuckDBPyConnection,
    display_name: str,
    bill_code: str,
    billing_week: str,
) -> pd.DataFrame:
    return conn.execute("""
        SELECT id, author, comment_text, created_at
        FROM skilled_tracker_comments
        WHERE display_name = ? AND bill_code = ? AND billing_week = ?
        ORDER BY created_at ASC
    """, [display_name, bill_code, billing_week]).df()


def add_tracker_comment(
    conn: duckdb.DuckDBPyConnection,
    display_name: str,
    bill_code: str,
    billing_week: str,
    comment_text: str,
    author: str,
) -> None:
    conn.execute("""
        INSERT INTO skilled_tracker_comments
            (id, display_name, bill_code, billing_week, comment_text, author)
        VALUES (nextval('seq_skilled_tracker_comments'), ?, ?, ?, ?, ?)
    """, [display_name, bill_code, billing_week, comment_text, author])



def update_tracker_comment(conn, comment_id: int, new_text: str) -> None:
    conn.execute(
        "UPDATE skilled_tracker_comments SET comment_text = ? WHERE id = ?",
        [new_text, comment_id]
    )

def delete_tracker_comment(conn, comment_id: int) -> None:
    conn.execute("DELETE FROM skilled_tracker_comments WHERE id = ?", [comment_id])

def deactivate_tracker_client(conn, display_name: str, bill_code: str, from_date: str) -> None:
    """Mark client inactive from from_date onwards. Historical data is preserved."""
    conn.execute("""
        UPDATE skilled_tracker_clients
        SET is_active = FALSE, deactivated_from = CAST(? AS DATE)
        WHERE display_name = ? AND bill_code = ?
    """, [from_date, display_name, bill_code])

def reactivate_tracker_client(conn, display_name: str, bill_code: str) -> None:
    """Reactivate a previously deactivated client."""
    conn.execute("""
        UPDATE skilled_tracker_clients
        SET is_active = TRUE, deactivated_from = NULL
        WHERE display_name = ? AND bill_code = ?
    """, [display_name, bill_code])

def get_all_tracker_clients(conn) -> "pd.DataFrame":
    """Return all clients including inactive ones — for management UI."""
    return conn.execute("""
        SELECT display_name, bill_code, service_type, is_active, deactivated_from, added_at
        FROM skilled_tracker_clients
        ORDER BY is_active DESC, display_name
    """).df()

def add_tracker_client(
    conn: duckdb.DuckDBPyConnection,
    display_name: str,
    bill_code: str,
    service_type: str,
    remittance_name: str | None = None,
) -> None:
    conn.execute("""
        INSERT INTO skilled_tracker_clients
            (id, display_name, bill_code, service_type, remittance_name, is_active)
        VALUES (nextval('seq_skilled_tracker_clients'), ?, ?, ?, ?, TRUE)
        ON CONFLICT (display_name, bill_code) DO UPDATE SET is_active = TRUE
    """, [display_name, bill_code, service_type, remittance_name])


def save_validation_run(
    conn: duckdb.DuckDBPyConnection,
    excel_filename: str,
    total: int,
    passed: int,
    failed: int,
    report_json: str,
) -> None:
    conn.execute("""
        INSERT INTO tracker_validation_runs
            (id, excel_filename, total_tests, passed_tests, failed_tests, report_json)
        VALUES (nextval('seq_tracker_validation_runs'), ?, ?, ?, ?, ?)
    """, [excel_filename, total, passed, failed, report_json])


def get_validation_history(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return conn.execute("""
        SELECT id, run_at, excel_filename, total_tests, passed_tests, failed_tests
        FROM tracker_validation_runs
        ORDER BY run_at DESC
        LIMIT 10
    """).df()
