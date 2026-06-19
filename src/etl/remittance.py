"""
src/etl/remittance.py
Parse the Remittance Report Master Excel file.

Sheet: "Remittance Report Template"
Row 0: metadata  ("Last uploaded remittance sheet is dated …")
Row 1: blank
Row 2: blank
Row 3: HEADERS  ← header_row=3
Row 4+: data

22 actual columns (0-indexed):
  0  Batch             float → int
  1  Date              string date  → payment_date
  2  Transaction       str
  3  Match Status      str
  4  Claim             float → str  (claim number)
  5  Transaction Type  str
  6  Charge            "$x,xxx.xx" string → float
  7  Payment           "$x,xxx.xx" string → float
  8  Allowed           "$x,xxx.xx" string → float
  9  First Name        str  ALL CAPS
  10 Last Name         str  ALL CAPS
  11 First DOS         string date
  12 Last DOS          string date
  13 TCN               str  (unique claim key)
  14 Billed Hrs        numeric
  15 Paid Hrs          numeric
  16 Hrs Remaining     numeric
  17 Client            "LAST FIRST" (space, no comma)
  18 Last Name, First  "LAST, FIRST" — our primary client name key
  19 Month             "3/" partial
  20 Insurance         actual payer name
  21 Payment Value     numeric (= col 7 as float)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_SHEET = "Remittance Report Template"
_HEADER_ROW = 3  # 0-indexed


def parse_remittance(path: Path) -> list[dict]:
    """
    Returns a list of dicts (one per claim row), with TCN deduplication:
    is_latest=True only for the record with the most-recent payment_date per TCN.
    """
    xl = pd.ExcelFile(path, engine="openpyxl")
    if _SHEET not in xl.sheet_names:
        raise ValueError(f"Sheet '{_SHEET}' not found in {path.name}")

    # Read with header at row 3 (skip rows 0-2)
    df = xl.parse(_SHEET, header=_HEADER_ROW, dtype=str)

    # DuckDB-friendly column renaming: keep positional access
    # (pandas will rename duplicate headers automatically, so we use iloc)
    records = []
    for _, row in df.iterrows():
        vals = row.tolist()
        if len(vals) < 14:
            continue

        tcn = _clean_str(_get(vals, 13))
        if not tcn:
            continue  # skip rows with no TCN

        rec = {
            "batch": _parse_int(_get(vals, 0)),
            "payment_date": _parse_date(_get(vals, 1)),
            "transaction": _clean_str(_get(vals, 2)),
            "match_status": _clean_str(_get(vals, 3)),
            "claim_number": _clean_str(_get(vals, 4)),
            "transaction_type": _clean_str(_get(vals, 5)),
            "charge_amount": _parse_dollar(_get(vals, 6)),
            "payment_amount": _parse_dollar(_get(vals, 7)),
            "allowed_amount": _parse_dollar(_get(vals, 8)),
            "client_first_name": _clean_str(_get(vals, 9)),
            "client_last_name": _clean_str(_get(vals, 10)),
            "first_dos": _parse_date(_get(vals, 11)),
            "last_dos": _parse_date(_get(vals, 12)),
            "tcn": tcn,
            "billed_hours": _parse_float(_get(vals, 14)),
            "paid_hours": _parse_float(_get(vals, 15)),
            "hours_remaining": _parse_float(_get(vals, 16)),
            "client_name_combined": _clean_str(_get(vals, 18)),  # "LAST, FIRST"
            "month_label": _clean_str(_get(vals, 19)),
            "insurance": _clean_str(_get(vals, 20)),
            "payment_value": _parse_float(_get(vals, 21)),
            "source_file": path.name,
            "is_latest": True,  # will be corrected below
        }
        records.append(rec)

    records = _deduplicate_tcns(records)
    return records


def filter_by_dos_range(records: list[dict], start: date, end: date) -> list[dict]:
    """
    Return only records whose service dates (first_dos .. last_dos) overlap
    the given week range.
    A claim overlaps if first_dos <= end AND last_dos >= start.
    """
    out = []
    for r in records:
        fd = r.get("first_dos")
        ld = r.get("last_dos")
        if fd is None and ld is None:
            continue
        fd = fd or ld
        ld = ld or fd
        if fd <= end and ld >= start:
            out.append(r)
    return out


def determine_remittance_record_care_type(r: dict) -> str:
    """
    Determine whether a remittance claim is Skilled or Unskilled.
    We check the hourly rate first:
    - If rate >= 30.0, it is Skilled.
    - If rate is between 0.1 and 30.0, it is Unskilled.
    - If rate is not determinable, we check the insurance label (PDN = Skilled).
    """
    billed_hrs = float(r.get("billed_hours") or 0.0)
    charge = float(r.get("charge_amount") or 0.0)
    paid_hrs = float(r.get("paid_hours") or 0.0)
    pay = float(r.get("payment_amount") or 0.0)
    
    rate = 0.0
    if billed_hrs != 0:
        rate = abs(charge / billed_hrs)
    elif paid_hrs != 0:
        rate = abs(pay / paid_hrs)
        
    if rate > 0.0:
        return "Skilled" if rate >= 30.0 else "Unskilled"
        
    ins = (r.get("insurance") or "").upper()
    if "PDN" in ins:
        return "Skilled"
    return "Unskilled"


def aggregate_remittance_hours(records: list[dict]) -> dict[tuple[str, str], dict]:
    """
    Group by (client_name_combined, care_type) → sum billed_hours and paid_hours (is_latest only),
    using the daily max billed per DOS range segment to deduplicate resubmissions.
    Returns: { (LAST, FIRST, care_type): {"client_name_combined": "LAST, FIRST", "care_type": care_type, "billed_hours": x, "paid_hours": y, "insurance": z} }
    """
    from collections import defaultdict
    # Group records by (client, care_type) and DOS segment (first_dos, last_dos)
    by_client_dos = defaultdict(lambda: defaultdict(list))
    for r in records:
        if not r.get("is_latest"):
            continue
        client = (r.get("client_name_combined") or "").strip().upper()
        if not client:
            continue
        care_type = determine_remittance_record_care_type(r)
        fd = r.get("first_dos")
        ld = r.get("last_dos")
        fd = fd or ld
        ld = ld or fd
        by_client_dos[(client, care_type)][(fd, ld)].append(r)
        
    agg: dict[tuple[str, str], dict] = {}
    for (client, care_type), segments in by_client_dos.items():
        total_billed = 0.0
        total_paid = 0.0
        final_ins = None
        orig_name = None
        max_billed_per_fd = {}
        
        for (fd, ld), group in segments.items():
            daily_billed = defaultdict(float)
            for r in group:
                p_date = r.get("payment_date")
                b_hrs = float(r.get("billed_hours") or 0.0)
                p_hrs = float(r.get("paid_hours") or 0.0)
                daily_billed[p_date] += b_hrs
                total_paid += p_hrs
                if r.get("insurance"):
                    final_ins = r.get("insurance")
                if r.get("client_name_combined"):
                    orig_name = r.get("client_name_combined")
                    
            segment_billed = max(daily_billed.values()) if daily_billed else 0.0
            segment_billed = max(segment_billed, 0.0)
            max_billed_per_fd[fd] = max(max_billed_per_fd.get(fd, 0.0), segment_billed)

        total_billed = sum(max_billed_per_fd.values())
        agg[(client, care_type)] = {
            "client_name_combined": orig_name,
            "care_type": care_type,
            "billed_hours": round(total_billed, 4),
            "paid_hours": round(total_paid, 4),
            "insurance": final_ins,
        }
    return agg



# ─── Private helpers ──────────────────────────────────────────────────────────

def _get(vals: list, idx: int) -> Any:
    try:
        return vals[idx]
    except IndexError:
        return None


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None


def _parse_date(val: Any) -> date | None:
    s = _clean_str(val)
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _parse_dollar(val: Any) -> float | None:
    s = _clean_str(val)
    if not s:
        return None
    s = re.sub(r"[$,\s]", "", s)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _parse_float(val: Any) -> float | None:
    s = _clean_str(val)
    if not s:
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def _parse_int(val: Any) -> int | None:
    f = _parse_float(val)
    return int(f) if f is not None else None


def _deduplicate_tcns(records: list[dict]) -> list[dict]:
    """
    Deduplicate identical records sharing (tcn, payment_date, transaction_type, batch).
    Keep only the first occurrence (or one of them) as is_latest=True.
    """
    seen = set()
    for r in records:
        key = (r["tcn"], r["payment_date"], r["transaction_type"], r["batch"])
        if key not in seen:
            seen.add(key)
            r["is_latest"] = True
        else:
            r["is_latest"] = False
    return records
