"""
src/etl/pipeline.py
Orchestrator: scan input directories → normalize → reconcile → write to DuckDB.
Supports incremental loading, archiving, and multi-week reconciliation.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
import duckdb

from src.config import cfg
from src.db.connection import get_persistent_conn
from src.db.schema import create_all
from src.etl.name_match import (
    build_copay_records,
    build_name_match_records,
    is_copay_client,
    load_copay_clients,
    load_name_match,
    resolve_client_name,
)
from src.etl.payroll import aggregate_payroll_hours, parse_payroll
from src.etl.reconciliation import compute_deltas, compute_result, TOLERANCE
from src.etl.remittance import (
    aggregate_remittance_hours,
    filter_by_dos_range,
    parse_remittance,
)
from src.etl.file_watcher import scan_input_dir, archive_file, compute_file_hash, PendingFile

log = logging.getLogger(__name__)

# Check if currently running under a test runner (e.g. pytest)
IS_TEST = "pytest" in sys.modules or "py.test" in sys.argv or any("test" in arg for arg in sys.argv)


# ── Normalization helpers ──────────────────────────────────────────────────────

def _normalize_client_key(name: str) -> str:
    """Normalize client name for matching: strip commas, collapse spaces, uppercase."""
    s = re.sub(r",", "", name)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


INSURANCE_MAP: dict[str, str] = {
    "United": "UHC",
    "Medicaid & PDN": "Medicaid",
    "Sentara & PDN": "Sentara",
}


def _normalize_insurance(insurance: str | None) -> str | None:
    """Map remittance insurance name to payroll insurance name."""
    if not insurance:
        return None
    return INSURANCE_MAP.get(insurance, insurance)


def get_week_start(d: date) -> date:
    """Align date to Wednesday-start week (Wednesday to Tuesday)."""
    offset = (d.weekday() - 2) % 7
    return d - timedelta(days=offset)


def get_week_end(start_date: date) -> date:
    """Wednesday to Tuesday: end is 6 days after start."""
    return start_date + timedelta(days=6)


def determine_care_type(client_name_raw: str | None, insurance: str | None) -> str:
    """PDN clients are skilled, others are unskilled."""
    client_name_raw = client_name_raw or ""
    insurance = insurance or ""
    if re.search(r"\b(?:LPN|RN)\b", client_name_raw, re.IGNORECASE) or "PDN" in insurance.upper():
        return "Skilled"
    return "Unskilled"


def load_name_match_from_db(conn: duckdb.DuckDBPyConnection) -> dict[str, str | None]:
    """Retrieve name mapping from DB as a fallback."""
    rows = conn.execute("SELECT payroll_name, remittance_name FROM name_match").fetchall()
    return {r[0].upper(): r[1] for r in rows}


def load_copay_clients_from_db(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """Retrieve copay clients list from DB as a fallback."""
    rows = conn.execute("SELECT client_name FROM copay_clients").fetchall()
    return {r[0].upper() for r in rows}


# ── Summary dataclass ──────────────────────────────────────────────────────────

@dataclass
class PipelineSummary:
    payroll_records: int = 0
    payroll_clients: int = 0
    remittance_records: int = 0
    remittance_filtered: int = 0
    name_match_entries: int = 0
    copay_entries: int = 0
    recon_rows: int = 0
    result_good: int = 0
    result_followup: int = 0
    result_no_payroll: int = 0
    unmatched_clients: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "payroll_records": self.payroll_records,
            "payroll_clients": self.payroll_clients,
            "remittance_records": self.remittance_records,
            "remittance_filtered": self.remittance_filtered,
            "name_match_entries": self.name_match_entries,
            "copay_entries": self.copay_entries,
            "recon_rows": self.recon_rows,
            "result_good": self.result_good,
            "result_followup": self.result_followup,
            "result_no_payroll": self.result_no_payroll,
            "unmatched_clients": self.unmatched_clients,
        }


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(
    payroll_path: Path | None = None,
    remittance_path: Path | None = None,
    recon_path: Path | None = None,
    db_path: Path | None = None,
) -> PipelineSummary:
    """
    Execute the incremental ETL pipeline:
    1. Scan input/ directory for new files or process explicit paths
    2. Write files incrementally to database using ON CONFLICT logic
    3. Rebuild reconciliation table for all active weeks
    4. Move processed files to archive (unless running tests)
    """
    db_path = db_path or cfg.db_path
    input_dir = cfg.input_dir
    archive_dir = cfg.archive_dir
    recon_path = recon_path or cfg.recon_file

    conn = get_persistent_conn(db_path)
    try:
        create_all(conn)

        # ── Load reference tables (always refresh if file exists) ──────────────────
        name_mapping = {}
        copay_set = set()
        if recon_path.exists():
            log.info("Loading name match + copay from: %s", recon_path)
            name_mapping = load_name_match(recon_path)
            copay_set = load_copay_clients(recon_path)
            _write_name_match(conn, name_mapping)
            _write_copay(conn, copay_set, recon_path)
        else:
            log.info("Reference Excel file not found. Loading from DB instead.")
            name_mapping = load_name_match_from_db(conn)
            copay_set = load_copay_clients_from_db(conn)

        # ── Find pending files ────────────────────────────────────────────────────
        files_to_process: list[PendingFile] = []
        
        # If explicit files were provided (e.g. from tests), bypass scanning
        if payroll_path or remittance_path:
            if payroll_path and payroll_path.exists():
                files_to_process.append(PendingFile(
                    path=payroll_path, filename=payroll_path.name,
                    file_type="payroll", file_hash=compute_file_hash(payroll_path),
                    status="New"
                ))
            if remittance_path and remittance_path.exists():
                files_to_process.append(PendingFile(
                    path=remittance_path, filename=remittance_path.name,
                    file_type="remittance", file_hash=compute_file_hash(remittance_path),
                    status="New"
                ))
        else:
            # Standard directory scanning mode
            files_to_process = scan_input_dir(input_dir, conn)
            # Only process new or modified files
            files_to_process = [f for f in files_to_process if f.status in ("New", "Changed")]

        # ── Ingest pending files ──────────────────────────────────────────────────
        for f in files_to_process:
            log.info("Ingesting new file: %s (%s)", f.filename, f.file_type)
            if f.file_type == "payroll":
                payroll_data = parse_payroll(f.path)
                _write_payroll_incremental(conn, payroll_data["records"])
                _write_employees(conn, payroll_data["employees"])
                
                # Register in database
                _mark_file_ingested(
                    conn, f.filename, "payroll", f.file_hash, len(payroll_data["records"]),
                    payroll_data.get("week_start_date"), payroll_data.get("week_end_date")
                )
                
                # Archive file (skip if running tests)
                if not (payroll_path or remittance_path) and not IS_TEST:
                    archive_file(f.path, archive_dir)

            elif f.file_type == "remittance":
                all_remittance = parse_remittance(f.path)
                _write_remittance_incremental(conn, all_remittance)
                
                # Calculate min/max service dates
                valid_first_dos = [r["first_dos"] for r in all_remittance if r.get("first_dos") is not None]
                valid_last_dos = [r["last_dos"] for r in all_remittance if r.get("last_dos") is not None]
                min_date = min(valid_first_dos) if valid_first_dos else None
                max_date = max(valid_last_dos) if valid_last_dos else None
                
                # Register in database
                _mark_file_ingested(
                    conn, f.filename, "remittance", f.file_hash, len(all_remittance),
                    week_start=min_date, week_end=max_date
                )
                
                # Archive file (skip if running tests)
                if not (payroll_path or remittance_path) and not IS_TEST:
                    archive_file(f.path, archive_dir)

        # ── Rebuild reconciliation and generate summary ───────────────────────────
        summary = rebuild_reconciliation(conn, name_mapping, copay_set)
        
        # Populate references counts
        summary.name_match_entries = len(name_mapping)
        summary.copay_entries = len(copay_set)

    finally:
        conn.close()

    return summary


# ── DB write helpers ───────────────────────────────────────────────────────────

def _write_name_match(conn, name_mapping: dict) -> None:
    conn.execute("DELETE FROM name_match")
    records = build_name_match_records(name_mapping)
    params = [[r["payroll_name"], r["remittance_name"]] for r in records]
    conn.executemany(
        """INSERT INTO name_match (id, payroll_name, remittance_name)
           VALUES (nextval('seq_name_match'), ?, ?)""",
        params,
    )
    conn.commit()
    log.info("Wrote %d name_match records", len(records))


def _write_copay(conn, copay_set: set, recon_path: Path) -> None:
    conn.execute("DELETE FROM copay_clients")
    records = build_copay_records(copay_set, recon_path)
    params = [[r["client_name"], r.get("insurance")] for r in records]
    conn.executemany(
        """INSERT INTO copay_clients (id, client_name, insurance)
           VALUES (nextval('seq_copay_clients'), ?, ?)""",
        params,
    )
    conn.commit()
    log.info("Wrote %d copay_clients records", len(records))


def _write_employees(conn, employees: list[dict]) -> None:
    seen_ids: set[str] = set()
    params = []
    for e in employees:
        emp_id = e.get("employee_id")
        if not emp_id or emp_id in seen_ids:
            continue
        seen_ids.add(emp_id)
        params.append([
            emp_id, e.get("last_name"), e.get("first_name"),
            e.get("full_name"), e.get("status")
        ])
        
    conn.executemany(
        """INSERT OR IGNORE INTO employees (employee_id, last_name, first_name, full_name, status)
           VALUES (?, ?, ?, ?, ?)""",
        params,
    )
    conn.commit()
    log.info("Upserted %d employee records", len(params))


def _write_payroll_incremental(conn, records: list[dict]) -> None:
    sql = """
        INSERT OR IGNORE INTO payroll (
            id, week_start_date, week_end_date, paycheck_date,
            client_name_raw, insurance, employee_name, employee_id,
            regular_hours, respite_hours, total_hours, source_file
        )
        VALUES (nextval('seq_payroll'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = [
        [
            r.get("week_start_date"), r.get("week_end_date"), r.get("paycheck_date"),
            r.get("client_name_raw"), r.get("insurance"), r.get("employee_name"),
            r.get("employee_id"), r.get("regular_hours"), r.get("respite_hours"),
            r.get("total_hours"), r.get("source_file")
        ]
        for r in records
    ]
    conn.executemany(sql, params)
    conn.commit()
    log.info("Incremental upserted %d payroll records", len(records))


def _write_remittance_incremental(conn, records: list[dict]) -> None:
    sql = """
        INSERT OR IGNORE INTO remittance (
            id, batch, payment_date, transaction, match_status,
            claim_number, transaction_type, charge_amount, payment_amount, allowed_amount,
            client_first_name, client_last_name, client_name_combined, first_dos, last_dos,
            tcn, billed_hours, paid_hours, hours_remaining, insurance, payment_value,
            month_label, source_file, is_latest
        )
        VALUES (nextval('seq_remittance'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = [
        [
            r.get("batch"), r.get("payment_date"), r.get("transaction"),
            r.get("match_status"), r.get("claim_number"), r.get("transaction_type"),
            r.get("charge_amount"), r.get("payment_amount"), r.get("allowed_amount"),
            r.get("client_first_name"), r.get("client_last_name"),
            r.get("client_name_combined"), r.get("first_dos"), r.get("last_dos"),
            r.get("tcn"), r.get("billed_hours"), r.get("paid_hours"),
            r.get("hours_remaining"), r.get("insurance"), r.get("payment_value"),
            r.get("month_label"), r.get("source_file"), r.get("is_latest")
        ]
        for r in records
    ]
    conn.executemany(sql, params)
    conn.commit()
    log.info("Incremental upserted %d remittance records", len(records))


def _mark_file_ingested(
    conn, filename: str, file_type: str, file_hash: str, row_count: int,
    week_start: date | None = None, week_end: date | None = None
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO ingested_files (id, filename, file_type, file_hash, row_count, week_start, week_end)
           VALUES (nextval('seq_ingested_files'), ?, ?, ?, ?, ?, ?)""",
        [filename, file_type, file_hash, row_count, week_start, week_end]
    )
    conn.commit()
    log.info("Registered file in ingested_files: %s", filename)


def _correct_reversal_rates(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Detect and correct Payer Reversal Rate Mismatch errors in the remittance table.
    We use a two-step lookup to find the correct hourly rate for a reversal:
    1. If the parent claim exists in the database (matching reversal TCN minus suffix),
       we use the parent claim's actual hourly rate.
    2. Otherwise, we fall back to the client's most common positive paid hourly rate
       (if they are classified as a Skilled client with standard rate >= 30.0).
    """
    log.info("Checking and correcting payer reversal rate mismatches in remittance...")
    
    # Step 1: Pre-calculate client standard positive rates for fallback
    query_standard_rates = """
        WITH client_rates AS (
            SELECT 
                client_name_combined,
                round(payment_amount / paid_hours, 2) AS rate,
                count(*) AS record_count
            FROM remittance
            WHERE payment_amount > 0 AND paid_hours > 0
            GROUP BY client_name_combined, rate
        ),
        ranked_rates AS (
            SELECT 
                client_name_combined,
                rate,
                ROW_NUMBER() OVER (PARTITION BY client_name_combined ORDER BY record_count DESC) as rn
            FROM client_rates
        )
        SELECT client_name_combined, rate
        FROM ranked_rates
        WHERE rn = 1 AND rate >= 30.0
    """
    skilled_client_rates = {}
    try:
        skilled_clients = conn.execute(query_standard_rates).fetchall()
        skilled_client_rates = {name: float(rate) for name, rate in skilled_clients}
    except Exception as e:
        log.warning("Could not calculate standard rates: %s", e)

    # Step 2: Query all potential reversal claims (where paid_hours < 0 or billed_hours < 0)
    try:
        reversals = conn.execute(
            """SELECT id, client_name_combined, tcn, payment_amount, charge_amount, paid_hours, billed_hours 
               FROM remittance 
               WHERE paid_hours < 0 OR billed_hours < 0"""
        ).fetchall()

        corrected_count = 0
        for r_id, client_name, tcn, p_amount, c_amount, paid_hours, billed_hours in reversals:
            # Skip if hours are 0/None or not negative
            p_hours_val = float(paid_hours or 0)
            b_hours_val = float(billed_hours or 0)
            
            # Implied rates of the reversal
            p_rate = abs(float(p_amount or 0) / p_hours_val) if p_hours_val != 0 else 0.0
            c_rate = abs(float(c_amount or 0) / b_hours_val) if b_hours_val != 0 else 0.0
            
            # We only correct if either rate is Unskilled (< 30.0) but standard rate is Skilled (>= 30.0)
            is_reversal_unskilled = (p_rate > 0.0 and p_rate < 30.0) or (c_rate > 0.0 and c_rate < 30.0)
            
            if not is_reversal_unskilled:
                continue

            # Try parent lookup first (TCN ends with R1/R2/A1 etc., strip last 2 chars)
            parent_tcn = tcn[:-2] if len(tcn) > 2 and (tcn.endswith("R1") or tcn.endswith("R2") or tcn.endswith("A1")) else None
            parent_rate = None
            if parent_tcn:
                parent_row = conn.execute(
                    """SELECT payment_amount, paid_hours, charge_amount, billed_hours 
                       FROM remittance WHERE tcn = ?""",
                    [parent_tcn]
                ).fetchone()
                if parent_row:
                    p_amt, p_hrs, c_amt, b_hrs = parent_row
                    if p_hrs and float(p_hrs) != 0:
                        parent_rate = abs(float(p_amt) / float(p_hrs))
                    elif b_hrs and float(b_hrs) != 0:
                        parent_rate = abs(float(c_amt) / float(b_hrs))

            # Fallback to client standard rate if parent not found/no rate
            if not parent_rate:
                parent_rate = skilled_client_rates.get(client_name)

            if parent_rate and parent_rate >= 30.0:
                # Correct the hours
                corrected_paid = round(float(p_amount or 0.0) / parent_rate, 4)
                corrected_billed = round(float(c_amount or 0.0) / parent_rate, 4)
                
                conn.execute(
                    """UPDATE remittance 
                       SET paid_hours = ?, billed_hours = ? 
                       WHERE id = ?""",
                    [corrected_paid, corrected_billed, r_id]
                )
                corrected_count += 1
                
        if corrected_count > 0:
            conn.commit()
            log.info("Corrected %d payer reversal rate mismatch records in remittance.", corrected_count)
    except Exception as e:
        log.error("Error correcting reversal rate mismatches: %s", e)


# ── Reconciliation rebuilding ─────────────────────────────────────────────────

def rebuild_reconciliation(
    conn: duckdb.DuckDBPyConnection,
    name_mapping: dict[str, str | None],
    copay_set: set[str],
) -> PipelineSummary:
    """
    Rebuild the entire reconciliation table based on the current contents of the
    payroll and remittance tables. Preserves analyst notes/overrides.
    """
    # Run the reversal rate correction step first
    _correct_reversal_rates(conn)

    log.info("Rebuilding reconciliation table...")


    # 1. Fetch and preserve existing overrides & comments
    existing_overrides = {}
    try:
        rows = conn.execute(
            """SELECT week_start_date, client_name_payroll, analyst_override, 
                      yash_comments, connie_comments, created_at 
               FROM reconciliation"""
        ).fetchall()
        for r in rows:
            ws_str = str(r[0])
            client_name = r[1]
            existing_overrides[(ws_str, client_name)] = {
                "analyst_override": r[2],
                "yash_comments": r[3],
                "connie_comments": r[4],
                "created_at": r[5],
            }
    except Exception as e:
        log.warning("Could not read existing overrides (this is expected on fresh schema): %s", e)

    # Backup review_actions and rebill_tracker before deleting reconciliation
    review_actions_data = []
    try:
        rows = conn.execute(
            """SELECT ra.id, r.week_start_date, r.client_name_payroll, ra.action, ra.performed_by, ra.performed_at, ra.notes
               FROM review_actions ra
               JOIN reconciliation r ON ra.reconciliation_id = r.id"""
        ).fetchall()
        for r_row in rows:
            review_actions_data.append({
                "id": r_row[0],
                "week_start_date": str(r_row[1]),
                "client_name_payroll": r_row[2],
                "action": r_row[3],
                "performed_by": r_row[4],
                "performed_at": r_row[5],
                "notes": r_row[6]
            })
    except Exception as e:
        log.warning("Could not backup review_actions: %s", e)

    rebill_tracker_data = []
    try:
        rows = conn.execute(
            """SELECT rt.id, r.week_start_date, r.client_name_payroll, rt.tcn, rt.denial_code, rt.rebill_date, rt.status, rt.notes, rt.created_at, rt.updated_at
               FROM rebill_tracker rt
               JOIN reconciliation r ON rt.reconciliation_id = r.id"""
        ).fetchall()
        for r_row in rows:
            rebill_tracker_data.append({
                "id": r_row[0],
                "week_start_date": str(r_row[1]),
                "client_name_payroll": r_row[2],
                "tcn": r_row[3],
                "denial_code": r_row[4],
                "rebill_date": r_row[5],
                "status": r_row[6],
                "notes": r_row[7],
                "created_at": r_row[8],
                "updated_at": r_row[9]
            })
    except Exception as e:
        log.warning("Could not backup rebill_tracker: %s", e)

    # Delete foreign key references so we can truncate reconciliation
    try:
        conn.execute("DELETE FROM review_actions")
        conn.execute("DELETE FROM rebill_tracker")
    except Exception as e:
        log.warning("Could not clear review_actions/rebill_tracker: %s", e)

    # 2. Re-create/clean the target table
    conn.execute("DELETE FROM reconciliation")
    conn.execute("DROP SEQUENCE IF EXISTS seq_reconciliation")
    conn.execute("CREATE SEQUENCE seq_reconciliation START 1")

    # 3. Determine all active weeks in the database
    active_weeks: set[tuple[date, date]] = set()

    # Weeks represented in payroll
    payroll_weeks = conn.execute(
        "SELECT DISTINCT week_start_date, week_end_date FROM payroll"
    ).fetchall()
    for ws, we in payroll_weeks:
        active_weeks.add((ws, we))

    # Weeks represented in remittance (map DOS to Wednesday-start cycles)
    remit_dos_dates = conn.execute(
        "SELECT DISTINCT first_dos FROM remittance WHERE is_latest = True AND first_dos IS NOT NULL"
    ).fetchall()
    for (fd,) in remit_dos_dates:
        ws = get_week_start(fd)
        we = get_week_end(ws)
        active_weeks.add((ws, we))

    sorted_weeks = sorted(list(active_weeks), key=lambda x: x[0], reverse=True)
    log.info("Active weeks to reconcile: %d", len(sorted_weeks))

    # 4. Load all records to avoid multiple subqueries (performance)
    # Get all payroll records
    raw_payroll = conn.execute(
        """SELECT week_start_date, week_end_date, paycheck_date, client_name_raw, insurance, total_hours 
           FROM payroll"""
    ).fetchall()

    # Get all remittance records including charges and payments to compute rates
    raw_remit = conn.execute(
        """SELECT first_dos, last_dos, client_name_combined, billed_hours, paid_hours, insurance, payment_date,
                  charge_amount, payment_amount
           FROM remittance WHERE is_latest = True"""
    ).fetchall()

    reconciliation_rows = []
    unmatched_clients = set()

    # Build reverse name mapping to match remittance-only names back to payroll names by care type
    reverse_mapping = {}
    for k, v in name_mapping.items():
        if v is not None:
            c_type = determine_care_type(k, None)
            reverse_mapping[(v.upper(), c_type)] = k

    # 5. Process week by week
    for week_start, week_end in sorted_weeks:
        week_start_str = str(week_start)
        
        # Filter payroll to this week and aggregate by client
        week_payroll = [r for r in raw_payroll if r[0] == week_start]
        has_payroll = len(week_payroll) > 0

        # Filter remittance to this week DOS range
        week_remit = []
        for r in raw_remit:
            fd, ld = r[0], r[1]
            if fd is None and ld is None:
                continue
            fd = fd or ld
            ld = ld or fd
            if fd <= week_end and ld >= week_start:
                week_remit.append(r)

        # Aggregate remittance records for this week using DOS segment-based deduplication grouped by (client, care_type)
        from collections import defaultdict
        by_client_dos = defaultdict(lambda: defaultdict(list))
        for r in week_remit:
            fd, ld, client_name, b_hrs, p_hrs, ins, p_date, charge, pay = r
            client = (client_name or "").strip().upper()
            if not client:
                continue
            fd = fd or ld
            ld = ld or fd
            
            # Determine care type dynamically
            rate = 0.0
            if b_hrs and float(b_hrs) != 0:
                rate = abs(float(charge or 0) / float(b_hrs))
            elif p_hrs and float(p_hrs) != 0:
                rate = abs(float(pay or 0) / float(p_hrs))
                
            if rate > 0.0:
                care_type = "Skilled" if rate >= 30.0 else "Unskilled"
            else:
                care_type = "Skilled" if (ins and "PDN" in ins.upper()) else "Unskilled"
                
            by_client_dos[(client, care_type)][(fd, ld)].append(r)

        aggregated_remit = {}
        for (client, care_type), segments in by_client_dos.items():
            total_billed = 0.0
            total_paid = 0.0
            final_ins = None
            for (fd, ld), group in segments.items():
                daily_billed = defaultdict(float)
                for r in group:
                    _, _, _, b_hrs, p_hrs, ins, p_date, _, _ = r
                    daily_billed[p_date] += float(b_hrs or 0.0)
                    total_paid += float(p_hrs or 0.0)
                    if ins:
                        final_ins = ins
                segment_billed = max(daily_billed.values()) if daily_billed else 0.0
                segment_billed = max(segment_billed, 0.0)
                total_billed += segment_billed
            aggregated_remit[(client, care_type)] = {
                "billed_hours": total_billed,
                "paid_hours": total_paid,
                "insurance": final_ins,
            }

        # Normalize keys for quick lookup
        remit_lookup = {}
        for (r_name, care_type), data in aggregated_remit.items():
            client_key = _normalize_client_key(r_name)
            remit_lookup[(client_key, care_type)] = data

        if has_payroll:
            # Standard Join Mode: Loop over payroll clients grouped by (client_name_raw, care_type)
            grouped_pay: dict[tuple[str, str], dict] = {}
            paycheck_date = None
            for r in week_payroll:
                paycheck_date = r[2]
                c_name = r[3]
                ins = r[4]
                care_type = determine_care_type(c_name, ins)
                key = (c_name, care_type)
                if key not in grouped_pay:
                    grouped_pay[key] = {
                        "client_name_raw": c_name,
                        "care_type": care_type,
                        "insurance": ins,
                        "total_hours": 0.0,
                    }
                grouped_pay[key]["total_hours"] += float(r[5] or 0.0)

            for (payroll_name, care_type), pay_data in grouped_pay.items():
                insurance = pay_data["insurance"]
                payroll_hrs = pay_data["total_hours"]

                # Resolve client name
                remit_name, match_status = resolve_client_name(payroll_name, name_mapping)
                copay = is_copay_client(payroll_name, copay_set)

                billed_hrs = 0.0
                paid_hrs = 0.0
                remit_insurance = None

                if match_status == "NOT_AVAILABLE":
                    pass
                elif remit_name:
                    client_key = _normalize_client_key(remit_name)
                    if (client_key, care_type) in remit_lookup:
                        rem_data = remit_lookup[(client_key, care_type)]
                        billed_hrs = rem_data["billed_hours"]
                        paid_hrs = rem_data["paid_hours"]
                        remit_insurance = rem_data["insurance"]
                else:
                    unmatched_clients.add(payroll_name)

                final_insurance = insurance or remit_insurance
                pvb, bvp, pvp = compute_deltas(payroll_hrs, billed_hrs, paid_hrs)
                result_simple, result_detailed = compute_result(
                    payroll_hrs, billed_hrs, paid_hrs, is_copay=copay
                )

                # Fetch preserved comments
                prev = existing_overrides.get((week_start_str, payroll_name), {})

                reconciliation_rows.append({
                    "week_start_date": week_start,
                    "week_end_date": week_end,
                    "paycheck_date": paycheck_date,
                    "insurance": final_insurance,
                    "client_name_payroll": payroll_name,
                    "client_name_remittance": remit_name,
                    "payroll_hours": payroll_hrs,
                    "billed_hours": billed_hrs,
                    "paid_hours": paid_hrs,
                    "payroll_vs_billed": pvb,
                    "billing_vs_paid": bvp,
                    "payroll_vs_paid": pvp,
                    "result_simple": result_simple,
                    "result_detailed": result_detailed,
                    "is_copay_client": copay,
                    "match_status": match_status,
                    "analyst_override": prev.get("analyst_override"),
                    "yash_comments": prev.get("yash_comments"),
                    "connie_comments": prev.get("connie_comments"),
                    "care_type": care_type,
                })
        else:
            # Remittance-Only Mode (No Payroll File)
            for (remit_name, care_type), rem_data in aggregated_remit.items():
                billed_hrs = rem_data["billed_hours"]
                paid_hrs = rem_data["paid_hours"]
                remit_insurance = rem_data["insurance"]

                # Reverse resolve client name to payroll if match exists, care-type aware
                payroll_name = reverse_mapping.get((remit_name.upper(), care_type))
                if not payroll_name:
                    fallback_keys = [k for (r_nm, ct), k in reverse_mapping.items() if r_nm == remit_name.upper()]
                    payroll_name = fallback_keys[0] if fallback_keys else remit_name
                copay = is_copay_client(payroll_name, copay_set)

                # Build row (payroll hours is None, status is 'No Payroll Data')
                # Deltas: payroll_vs_billed = None, billing_vs_paid = billed - paid
                pvb = None
                bvp = round(billed_hrs - paid_hrs, 4)
                pvp = None
                
                prev = existing_overrides.get((week_start_str, payroll_name), {})

                # Reconcile billed vs paid for remittance-only weeks
                bvp_abs = abs(bvp)
                if billed_hrs < 0 or paid_hrs < 0:
                    res_simple = "Follow up"
                    res_detailed = "Payer Reversal"
                elif bvp_abs <= TOLERANCE:
                    res_simple = "Good"
                    res_detailed = None
                else:
                    res_simple = "Follow up"
                    if paid_hrs < 1:
                        res_detailed = "Not Paid"
                    elif paid_hrs < billed_hrs:
                        res_detailed = "Paid Less"
                    else:
                        res_detailed = "Paid Excess"


                reconciliation_rows.append({
                    "week_start_date": week_start,
                    "week_end_date": week_end,
                    "paycheck_date": None,
                    "insurance": remit_insurance,
                    "client_name_payroll": payroll_name,
                    "client_name_remittance": remit_name,
                    "payroll_hours": None,
                    "billed_hours": billed_hrs,
                    "paid_hours": paid_hrs,
                    "payroll_vs_billed": pvb,
                    "billing_vs_paid": bvp,
                    "payroll_vs_paid": pvp,
                    "result_simple": res_simple,
                    "result_detailed": res_detailed,
                    "is_copay_client": copay,
                    "match_status": "MATCHED" if payroll_name != remit_name else "UNMATCHED",
                    "analyst_override": prev.get("analyst_override"),
                    "yash_comments": prev.get("yash_comments"),
                    "connie_comments": prev.get("connie_comments"),
                    "care_type": care_type,
                })

    # 6. Bulk Insert to reconciliation table
    _write_reconciliation_rows(conn, reconciliation_rows)

    # Restore review_actions and rebill_tracker with new reconciliation IDs
    if review_actions_data or rebill_tracker_data:
        log.info("Restoring review_actions and rebill_tracker with new reconciliation IDs...")
        new_id_map = {}
        db_rows = conn.execute("SELECT id, week_start_date, client_name_payroll FROM reconciliation").fetchall()
        for r_id, ws, client in db_rows:
            if client:
                new_id_map[(str(ws), client.upper())] = r_id

        # Restore review_actions
        if review_actions_data:
            params = []
            for ra in review_actions_data:
                if ra["client_name_payroll"]:
                    new_recon_id = new_id_map.get((ra["week_start_date"], ra["client_name_payroll"].upper()))
                    if new_recon_id:
                        params.append([
                            ra["id"], new_recon_id, ra["action"], ra["performed_by"], ra["performed_at"], ra["notes"]
                        ])
            if params:
                conn.executemany(
                    """INSERT INTO review_actions (id, reconciliation_id, action, performed_by, performed_at, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    params
                )
                
        # Restore rebill_tracker
        if rebill_tracker_data:
            params = []
            for rt in rebill_tracker_data:
                if rt["client_name_payroll"]:
                    new_recon_id = new_id_map.get((rt["week_start_date"], rt["client_name_payroll"].upper()))
                    if new_recon_id:
                        params.append([
                            rt["id"], new_recon_id, rt["tcn"], rt["denial_code"], rt["rebill_date"], rt["status"], rt["notes"], rt["created_at"], rt["updated_at"]
                        ])
            if params:
                conn.executemany(
                    """INSERT INTO rebill_tracker (id, reconciliation_id, tcn, denial_code, rebill_date, status, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    params
                )

    # 7. Collect database status counts for the summary report
    summary = PipelineSummary()
    summary.payroll_records = conn.execute("SELECT COUNT(*) FROM payroll").fetchone()[0]
    summary.payroll_clients = conn.execute("SELECT COUNT(DISTINCT client_name_raw) FROM payroll").fetchone()[0]
    summary.remittance_records = conn.execute("SELECT COUNT(*) FROM remittance").fetchone()[0]
    summary.recon_rows = conn.execute("SELECT COUNT(*) FROM reconciliation").fetchone()[0]
    
    summary.result_good = conn.execute("SELECT COUNT(*) FROM reconciliation WHERE result_simple = 'Good'").fetchone()[0]
    summary.result_followup = conn.execute("SELECT COUNT(*) FROM reconciliation WHERE result_simple = 'Follow up'").fetchone()[0]
    summary.result_no_payroll = conn.execute("SELECT COUNT(*) FROM reconciliation WHERE result_simple IN ('No Payroll Hours', 'No Payroll Data')").fetchone()[0]
    summary.unmatched_clients = list(unmatched_clients)

    log.info(
        "Reconciliation rebuild done: %d rows (Good: %d, Follow up: %d, No Payroll Data: %d)",
        summary.recon_rows,
        summary.result_good,
        summary.result_followup,
        summary.result_no_payroll
    )
    return summary


def _write_reconciliation_rows(conn, rows: list[dict]) -> None:
    if not rows:
        log.info("No records to insert into reconciliation")
        return

    sql = """
        INSERT INTO reconciliation (
            id, week_start_date, week_end_date, paycheck_date,
            insurance, client_name_payroll, client_name_remittance,
            payroll_hours, billed_hours, paid_hours,
            payroll_vs_billed, billing_vs_paid, payroll_vs_paid,
            result_simple, result_detailed, is_copay_client, match_status,
            analyst_override, yash_comments, connie_comments, care_type
        )
        VALUES (nextval('seq_reconciliation'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = [
        [
            r.get("week_start_date"), r.get("week_end_date"), r.get("paycheck_date"),
            r.get("insurance"), r.get("client_name_payroll"), r.get("client_name_remittance"),
            r.get("payroll_hours"), r.get("billed_hours"), r.get("paid_hours"),
            r.get("payroll_vs_billed"), r.get("billing_vs_paid"), r.get("payroll_vs_paid"),
            r.get("result_simple"), r.get("result_detailed"), r.get("is_copay_client"),
            r.get("match_status"), r.get("analyst_override"), r.get("yash_comments"),
            r.get("connie_comments"), r.get("care_type")
        ]
        for r in rows
    ]
    conn.executemany(sql, params)
    conn.commit()
    log.info("Inserted %d records into reconciliation", len(rows))


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    summary = run_pipeline()
    print("\n=== Pipeline Summary ===")
    print(json.dumps(summary.as_dict(), indent=2, default=str))
