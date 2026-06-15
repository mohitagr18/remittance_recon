"""
src/etl/payroll.py
Parse the payroll Excel file.

Sheet structure (03062026 sheet):
  Row 1  : Metadata  — "Paycheck Date:" | date
  Row 2  : Metadata  — "Work Week:"     | start_date | "to" | None | end_date
  Row 3  : Headers   — Client | Insurance | Employee | Paylocity Emp ID | Regular hrs | Respite hrs | Total Hrs | ...
  Row 4+ : Data      — alternates between summary rows (no Insurance/Employee)
                       and detail rows (with Insurance/Employee)

The detail rows carry:
  col A (0) : client name  (repeated from summary row)
  col B (1) : insurance
  col C (2) : employee name
  col D (3) : employee ID (float → int)
  col E (4) : regular hours
  col F (5) : respite hours
  col G (6) : total hours (formula; we compute from E+F instead)

We only load DETAIL rows (those where col B has an insurance value) and
ignore the aggregation/summary rows.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ─── Public API ───────────────────────────────────────────────────────────────


def parse_payroll(path: Path) -> dict[str, Any]:
    """
    Returns:
        {
            "paycheck_date":  date,
            "week_start_date": date,
            "week_end_date":   date,
            "records":         list[dict],   # one per aide-client pair
            "employees":       list[dict],   # from Paylocity Mapping sheet
            "source_file":     str,
        }
    """
    xl = pd.ExcelFile(path, engine="openpyxl")

    # Detect the data sheet: any sheet whose name looks like MMDDYYYY
    data_sheet = _detect_data_sheet(xl.sheet_names)

    raw = xl.parse(data_sheet, header=None, dtype=str)

    # ── Extract dates from rows 0 and 1 (0-indexed) ──────────────────────────
    # Robust paycheck_date extraction
    paycheck_date = None
    row_0_vals = list(raw.iloc[0].values)
    for idx, val in enumerate(row_0_vals):
        if val and "Paycheck Date:" in str(val):
            for offset in range(1, 6):
                if idx + offset < len(row_0_vals):
                    parsed_dt = _parse_date_cell(row_0_vals[idx + offset])
                    if parsed_dt:
                        paycheck_date = parsed_dt
                        break
            break

    # Robust week start/end extraction
    week_start_date = None
    week_end_date = None
    row_1_vals = list(raw.iloc[1].values)
    for idx, val in enumerate(row_1_vals):
        if val and "Work Week:" in str(val):
            dates_found = []
            for offset in range(1, 10):
                if idx + offset < len(row_1_vals):
                    parsed_dt = _parse_date_cell(row_1_vals[idx + offset])
                    if parsed_dt:
                        dates_found.append(parsed_dt)
            if len(dates_found) >= 2:
                week_start_date = dates_found[0]
                week_end_date = dates_found[1]
            elif len(dates_found) == 1:
                week_start_date = dates_found[0]
            break

    # ── Parse detail rows (start at row index 3 = Excel row 4) ───────────────
    records = []
    for _, row in raw.iloc[3:].iterrows():
        client = _clean_str(row.get(0))
        insurance = _clean_str(row.get(1))
        employee = _clean_str(row.get(2))
        emp_id_raw = row.get(3)
        regular_raw = row.get(4)
        respite_raw = row.get(5)

        # Detail rows must have an insurance value and a client name
        if not insurance or not client:
            continue
        # Skip formula leftovers
        if insurance.startswith("=") or client.startswith("="):
            continue

        # Parse hours — formulas come through as strings like "=SUM(...)"
        regular = _parse_hours(regular_raw)
        respite = _parse_hours(respite_raw)
        total = round((regular or 0) + (respite or 0), 2)

        emp_id = _parse_emp_id(emp_id_raw)

        records.append(
            {
                "client_name_raw": client.strip(),
                "insurance": insurance.strip(),
                "employee_name": employee.strip() if employee else None,
                "employee_id": emp_id,
                "regular_hours": regular,
                "respite_hours": respite,
                "total_hours": total,
                "paycheck_date": paycheck_date,
                "week_start_date": week_start_date,
                "week_end_date": week_end_date,
                "source_file": path.name,
            }
        )

    # ── Employee master from Paylocity Mapping ────────────────────────────────
    employees = _parse_employee_master(xl)

    return {
        "paycheck_date": paycheck_date,
        "week_start_date": week_start_date,
        "week_end_date": week_end_date,
        "records": records,
        "employees": employees,
        "source_file": path.name,
    }


def aggregate_payroll_hours(records: list[dict]) -> list[dict]:
    """
    Aggregate total hours per (client_name_raw, insurance) across all aides.
    Returns one dict per unique client.
    """
    agg: dict[tuple, dict] = {}
    for r in records:
        key = (r["client_name_raw"], r["insurance"])
        if key not in agg:
            agg[key] = {
                "client_name_raw": r["client_name_raw"],
                "insurance": r["insurance"],
                "total_hours": 0.0,
                "regular_hours": 0.0,
                "respite_hours": 0.0,
                "paycheck_date": r["paycheck_date"],
                "week_start_date": r["week_start_date"],
                "week_end_date": r["week_end_date"],
                "source_file": r["source_file"],
                "employees": [],
            }
        agg[key]["total_hours"] = round(agg[key]["total_hours"] + (r["total_hours"] or 0), 2)
        agg[key]["regular_hours"] = round(agg[key]["regular_hours"] + (r["regular_hours"] or 0), 2)
        agg[key]["respite_hours"] = round(agg[key]["respite_hours"] + (r["respite_hours"] or 0), 2)
        if r.get("employee_name"):
            agg[key]["employees"].append(r["employee_name"])

    return list(agg.values())


# ─── Private helpers ──────────────────────────────────────────────────────────

_MMDDYYYY = re.compile(r"^\d{8}$")


def _detect_data_sheet(sheet_names: list[str]) -> str:
    for name in sheet_names:
        if _MMDDYYYY.match(name.strip()):
            return name
    # Fallback: first sheet whose name contains digits
    for name in sheet_names:
        if any(c.isdigit() for c in name):
            return name
    raise ValueError(f"Cannot detect payroll data sheet from: {sheet_names}")


def _parse_date_cell(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date() if hasattr(val, "date") else val
    s = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _clean_str(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None


def _parse_hours(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    if s.startswith("="):
        return None  # formula cell — will be recomputed
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _parse_emp_id(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.startswith("=") or s == " ":
        return None
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        return s


def _parse_employee_master(xl: pd.ExcelFile) -> list[dict]:
    """Parse the Paylocity Mapping sheet — headers are on row 2 (0-indexed row 1)."""
    if "Paylocity Mapping" not in xl.sheet_names:
        return []

    raw = xl.parse("Paylocity Mapping", header=None, dtype=str)
    employees = []
    for _, row in raw.iloc[2:].iterrows():  # data starts at row 3 (0-indexed 2)
        last = _clean_str(row.get(1))
        first = _clean_str(row.get(2))
        emp_id = _parse_emp_id(row.get(4))
        status = _clean_str(row.get(5))
        if not last and not first:
            continue
        employees.append(
            {
                "employee_id": emp_id,
                "last_name": last,
                "first_name": first,
                "full_name": f"{last}, {first}" if last and first else (last or first),
                "status": status,
            }
        )
    return employees
