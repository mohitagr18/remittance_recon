"""
src/etl/pipeline.py
Orchestrator: read → normalize → reconcile → write to DuckDB.

Usage:
    from src.etl.pipeline import run_pipeline
    summary = run_pipeline()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

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
from src.etl.reconciliation import compute_deltas, compute_result
from src.etl.remittance import (
    aggregate_remittance_hours,
    filter_by_dos_range,
    parse_remittance,
)

log = logging.getLogger(__name__)


# ── Normalization helper ───────────────────────────────────────────────────────

import re

def _normalize_client_key(name: str) -> str:
    """Normalize client name for matching: strip commas, collapse spaces, uppercase."""
    s = re.sub(r",", "", name)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


# ── Insurance name mapping ─────────────────────────────────────────────────────
# Remittance file uses different insurance names than payroll.
# This maps remittance insurance → payroll insurance for matching.

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
    Execute the full ETL pipeline:
    1. Parse all three source files
    2. Build name-match and copay lookup structures
    3. Join payroll + remittance on normalized client name
    4. Compute reconciliation flags
    5. Write everything to DuckDB
    6. Return summary statistics
    """
    payroll_path = payroll_path or cfg.payroll_file
    remittance_path = remittance_path or cfg.remittance_file
    recon_path = recon_path or cfg.recon_file
    db_path = db_path or cfg.db_path

    summary = PipelineSummary()

    # ── 1. Parse source files ──────────────────────────────────────────────────
    log.info("Parsing payroll: %s", payroll_path)
    payroll_data = parse_payroll(payroll_path)
    summary.payroll_records = len(payroll_data["records"])

    log.info("Parsing remittance: %s", remittance_path)
    all_remittance = parse_remittance(remittance_path)
    summary.remittance_records = len(all_remittance)

    log.info("Loading name match + copay from: %s", recon_path)
    name_mapping = load_name_match(recon_path)
    copay_set = load_copay_clients(recon_path)
    summary.name_match_entries = len(name_mapping)
    summary.copay_entries = len(copay_set)

    # ── 2. Aggregate payroll hours per client ──────────────────────────────────
    aggregated_payroll = aggregate_payroll_hours(payroll_data["records"])
    summary.payroll_clients = len(aggregated_payroll)
    log.info("Aggregated payroll: %d unique clients", len(aggregated_payroll))

    # ── 3. Filter remittance to the target week and aggregate ──────────────────
    week_start = payroll_data["week_start_date"]
    week_end = payroll_data["week_end_date"]
    log.info("Filtering remittance to week %s – %s", week_start, week_end)

    filtered_remittance = filter_by_dos_range(all_remittance, week_start, week_end)
    summary.remittance_filtered = len(filtered_remittance)
    log.info("Remittance records in week range: %d", len(filtered_remittance))

    # Normalize insurance in filtered remittance records
    for rec in filtered_remittance:
        rec["insurance_normalized"] = _normalize_insurance(rec.get("insurance"))

    aggregated_remittance = aggregate_remittance_hours(filtered_remittance)

    # ── 4. Build remittance lookup: normalized_client_name → hours ──────────────
    # Match by client name only (same as Excel recon). Insurance mapping is used
    # only for normalizing the stored insurance value, not for filtering.
    remit_lookup: dict[str, dict] = {}
    for remit_name, data in aggregated_remittance.items():
        client_key = _normalize_client_key(remit_name)
        remit_lookup[client_key] = data

    # ── 5. Join and reconcile ──────────────────────────────────────────────────
    reconciliation_rows = []
    unmatched = []

    for pr in aggregated_payroll:
        payroll_name = pr["client_name_raw"]
        insurance = pr.get("insurance")
        payroll_hrs = pr["total_hours"] or 0.0

        # Resolve name
        remit_name, match_status = resolve_client_name(payroll_name, name_mapping)
        copay = is_copay_client(payroll_name, copay_set)

        # Look up remittance hours
        billed_hrs = 0.0
        paid_hrs = 0.0
        remit_insurance = None

        if match_status == "NOT_AVAILABLE":
            # Skip non-billable clients — they still appear with 0 billed/paid
            pass
        elif remit_name:
            client_key = _normalize_client_key(remit_name)
            if client_key in remit_lookup:
                rem_data = remit_lookup[client_key]
                billed_hrs = rem_data["billed_hours"] or 0.0
                paid_hrs = rem_data["paid_hours"] or 0.0
                remit_insurance = rem_data.get("insurance")
            else:
                # Name resolved but not found in remittance — could be no claims this week
                if match_status == "MATCHED":
                    pass  # valid — just no remittance data
        else:
            # UNMATCHED
            unmatched.append(payroll_name)

        # Use payroll insurance; fall back to remittance insurance
        final_insurance = insurance or remit_insurance

        # Compute deltas
        pvb, bvp, pvp = compute_deltas(payroll_hrs, billed_hrs, paid_hrs)

        # Compute result
        result_simple, result_detailed = compute_result(
            payroll_hrs, billed_hrs, paid_hrs, is_copay=copay
        )

        reconciliation_rows.append({
            "week_start_date": week_start,
            "week_end_date": week_end,
            "paycheck_date": payroll_data["paycheck_date"],
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
            "analyst_override": None,
            "yash_comments": None,
            "connie_comments": None,
        })

        # Tally results
        if result_simple == "Good":
            summary.result_good += 1
        elif result_simple == "Follow up":
            summary.result_followup += 1
        elif result_simple == "No Payroll Hours":
            summary.result_no_payroll += 1

    summary.recon_rows = len(reconciliation_rows)
    summary.unmatched_clients = unmatched

    log.info(
        "Reconciliation complete: %d rows (Good: %d, Follow up: %d, No Payroll: %d, Unmatched: %d)",
        summary.recon_rows,
        summary.result_good,
        summary.result_followup,
        summary.result_no_payroll,
        len(unmatched),
    )

    # ── 6. Write to DuckDB ─────────────────────────────────────────────────────
    log.info("Writing to DuckDB: %s", db_path)
    conn = get_persistent_conn(db_path)
    try:
        create_all(conn)

        # Write reference tables
        _write_name_match(conn, name_mapping)
        _write_copay(conn, copay_set, recon_path)
        _write_employees(conn, payroll_data["employees"])

        # Write fact tables
        _write_payroll(conn, payroll_data["records"])
        _write_remittance(conn, all_remittance)

        # Write reconciliation
        _write_reconciliation(conn, reconciliation_rows)

        log.info("All tables written to DuckDB successfully")
    finally:
        conn.close()

    return summary


# ── DB write helpers ───────────────────────────────────────────────────────────


def _write_name_match(conn, name_mapping: dict) -> None:
    conn.execute("DELETE FROM name_match")
    records = build_name_match_records(name_mapping)
    for r in records:
        conn.execute(
            """INSERT INTO name_match (id, payroll_name, remittance_name)
               VALUES (nextval('seq_name_match'), ?, ?)""",
            [r["payroll_name"], r["remittance_name"]],
        )
    conn.commit()
    log.info("Wrote %d name_match records", len(records))


def _write_copay(conn, copay_set: set, recon_path: Path) -> None:
    conn.execute("DELETE FROM copay_clients")
    records = build_copay_records(copay_set, recon_path)
    for r in records:
        conn.execute(
            """INSERT INTO copay_clients (id, client_name, insurance)
               VALUES (nextval('seq_copay_clients'), ?, ?)""",
            [r["client_name"], r.get("insurance")],
        )
    conn.commit()
    log.info("Wrote %d copay_clients records", len(records))


def _write_employees(conn, employees: list[dict]) -> None:
    conn.execute("DELETE FROM employees")
    seen_ids: set[str] = set()
    written = 0
    for e in employees:
        emp_id = e.get("employee_id")
        if not emp_id or emp_id in seen_ids:
            continue
        seen_ids.add(emp_id)
        conn.execute(
            """INSERT INTO employees (employee_id, last_name, first_name, full_name, status)
               VALUES (?, ?, ?, ?, ?)""",
            [emp_id, e.get("last_name"), e.get("first_name"),
             e.get("full_name"), e.get("status")],
        )
        written += 1
    conn.commit()
    log.info("Wrote %d employee records (skipped %d duplicates)", written, len(employees) - written)


def _write_payroll(conn, records: list[dict]) -> None:
    conn.execute("DELETE FROM payroll")
    for r in records:
        conn.execute(
            """INSERT INTO payroll (id, week_start_date, week_end_date, paycheck_date,
               client_name_raw, insurance, employee_name, employee_id,
               regular_hours, respite_hours, total_hours, source_file)
               VALUES (nextval('seq_payroll'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                r.get("week_start_date"), r.get("week_end_date"), r.get("paycheck_date"),
                r.get("client_name_raw"), r.get("insurance"), r.get("employee_name"),
                r.get("employee_id"), r.get("regular_hours"), r.get("respite_hours"),
                r.get("total_hours"), r.get("source_file"),
            ],
        )
    conn.commit()
    log.info("Wrote %d payroll records", len(records))


def _write_remittance(conn, records: list[dict]) -> None:
    conn.execute("DELETE FROM remittance")
    for r in records:
        conn.execute(
            """INSERT INTO remittance (id, batch, payment_date, transaction, match_status,
               claim_number, transaction_type, charge_amount, payment_amount, allowed_amount,
               client_first_name, client_last_name, client_name_combined, first_dos, last_dos,
               tcn, billed_hours, paid_hours, hours_remaining, insurance, payment_value,
               month_label, source_file, is_latest)
               VALUES (nextval('seq_remittance'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                r.get("batch"), r.get("payment_date"), r.get("transaction"),
                r.get("match_status"), r.get("claim_number"), r.get("transaction_type"),
                r.get("charge_amount"), r.get("payment_amount"), r.get("allowed_amount"),
                r.get("client_first_name"), r.get("client_last_name"),
                r.get("client_name_combined"), r.get("first_dos"), r.get("last_dos"),
                r.get("tcn"), r.get("billed_hours"), r.get("paid_hours"),
                r.get("hours_remaining"), r.get("insurance"), r.get("payment_value"),
                r.get("month_label"), r.get("source_file"), r.get("is_latest"),
            ],
        )
    conn.commit()
    log.info("Wrote %d remittance records", len(records))


def _write_reconciliation(conn, rows: list[dict]) -> None:
    conn.execute("DELETE FROM reconciliation")
    for r in rows:
        conn.execute(
            """INSERT INTO reconciliation (id, week_start_date, week_end_date, paycheck_date,
               insurance, client_name_payroll, client_name_remittance,
               payroll_hours, billed_hours, paid_hours,
               payroll_vs_billed, billing_vs_paid, payroll_vs_paid,
               result_simple, result_detailed, is_copay_client, match_status,
               analyst_override, yash_comments, connie_comments)
               VALUES (nextval('seq_reconciliation'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?)""",
            [
                r.get("week_start_date"), r.get("week_end_date"), r.get("paycheck_date"),
                r.get("insurance"), r.get("client_name_payroll"),
                r.get("client_name_remittance"), r.get("payroll_hours"),
                r.get("billed_hours"), r.get("paid_hours"), r.get("payroll_vs_billed"),
                r.get("billing_vs_paid"), r.get("payroll_vs_paid"),
                r.get("result_simple"), r.get("result_detailed"),
                r.get("is_copay_client"), r.get("match_status"),
                r.get("analyst_override"), r.get("yash_comments"),
                r.get("connie_comments"),
            ],
        )
    conn.commit()
    log.info("Wrote %d reconciliation records", len(rows))


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    summary = run_pipeline()
    print("\n=== Pipeline Summary ===")
    print(json.dumps(summary.as_dict(), indent=2, default=str))
