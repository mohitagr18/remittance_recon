"""
src/etl/name_match.py
Name normalisation engine.

Loads the Name Match table from the Weekly Recon file's "Name Match" sheet.
Builds a lookup: UPPER(payroll_name_stripped) → remittance_name

Key normalisation rules (derived from inspecting the actual table):
  1. Case-insensitive lookup
  2. Trailing role suffixes stripped: " PCA", " LPN", " RN", " (LPN)", " (RN)"
  3. Trailing whitespace stripped
  4. Double-spaces collapsed to single
  5. NULL / "Not Available" remittance_name → match_status = NOT_AVAILABLE

Also loads the Copay list from the "Copay" sheet.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

# Role suffixes that may appear at the end of payroll names
_ROLE_SUFFIX = re.compile(
    r"\s+(?:PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$",
    re.IGNORECASE,
)

_NAME_MATCH_SHEET = "Name Match"
_COPAY_SHEET = "Copay"


# ─── Public API ───────────────────────────────────────────────────────────────


def load_name_match(recon_path: Path) -> dict[str, str | None]:
    """
    Returns mapping: UPPER(stripped_payroll_name) → remittance_name | None.
    None means the client maps to "Not Available" (private/non-billable).
    """
    xl = pd.ExcelFile(recon_path, engine="openpyxl")
    if _NAME_MATCH_SHEET not in xl.sheet_names:
        return {}

    df = xl.parse(_NAME_MATCH_SHEET, header=0, dtype=str)
    # Expected columns: [0] Payroll Name, [1] xLOOKUP NAMES / remittance name
    mapping: dict[str, str | None] = {}
    for _, row in df.iterrows():
        payroll = _clean(row.iloc[0]) if len(row) > 0 else None
        remit = _clean(row.iloc[1]) if len(row) > 1 else None
        if not payroll:
            continue
        # Canonical key: strip role suffix, uppercase, collapse spaces
        key = _make_key(payroll)
        if not remit or remit.upper() in ("NOT AVAILABLE", "N/A", "NA"):
            mapping[key] = None
        else:
            mapping[key] = remit
    return mapping


def load_copay_clients(recon_path: Path) -> set[str]:
    """
    Returns a set of UPPER(stripped_payroll_names) that are on the copay list.
    The Copay sheet uses payroll names (may include role suffix).
    """
    xl = pd.ExcelFile(recon_path, engine="openpyxl")
    if _COPAY_SHEET not in xl.sheet_names:
        return set()

    df = xl.parse(_COPAY_SHEET, header=None, dtype=str)
    copay: set[str] = set()
    for _, row in df.iterrows():
        for val in row:
            name = _clean(val)
            if name and len(name) > 3:
                copay.add(_make_key(name))
    return copay


def resolve_client_name(
    payroll_name: str,
    mapping: dict[str, str | None],
) -> tuple[str | None, str]:
    """
    Map a raw payroll name → (remittance_name | None, match_status).
    match_status is one of: "MATCHED" | "UNMATCHED" | "NOT_AVAILABLE"
    """
    key = _make_key(payroll_name)
    if key in mapping:
        remit = mapping[key]
        if remit is None:
            return None, "NOT_AVAILABLE"
        return remit, "MATCHED"
    # Try with suffix stripped
    stripped = _strip_suffix(payroll_name)
    key2 = _make_key(stripped)
    if key2 in mapping:
        remit = mapping[key2]
        if remit is None:
            return None, "NOT_AVAILABLE"
        return remit, "MATCHED"
    return None, "UNMATCHED"


def is_copay_client(payroll_name: str, copay_set: set[str]) -> bool:
    key = _make_key(payroll_name)
    if key in copay_set:
        return True
    stripped = _make_key(_strip_suffix(payroll_name))
    return stripped in copay_set


def build_name_match_records(mapping: dict[str, str | None]) -> list[dict]:
    """Convert the mapping dict to a list of dicts for DB insertion."""
    return [
        {"payroll_name": k, "remittance_name": v}
        for k, v in mapping.items()
    ]


def build_copay_records(copay_set: set[str], recon_path: Path) -> list[dict]:
    """Read copay sheet again properly to get insurance labels."""
    xl = pd.ExcelFile(recon_path, engine="openpyxl")
    if _COPAY_SHEET not in xl.sheet_names:
        return []

    df = xl.parse(_COPAY_SHEET, header=None, dtype=str)
    records = []

    # Single-column sheet: all rows are client names, no insurance grouping
    if df.shape[1] <= 1:
        for _, row in df.iterrows():
            name = _clean(row.iloc[0]) if len(row) > 0 else None
            if name:
                records.append({"client_name": name, "insurance": None})
        return records

    # Multi-column sheet: rows with data in col 1+ are client rows;
    # rows with only col 0 populated are insurance group headers
    current_insurance = None
    for _, row in df.iterrows():
        first_val = _clean(row.iloc[0]) if len(row) > 0 else None
        if not first_val:
            continue
        has_data_in_other_cols = any(_clean(v) is not None for v in row.iloc[1:])
        if not has_data_in_other_cols:
            current_insurance = first_val
            continue
        records.append({"client_name": first_val, "insurance": current_insurance})
    return records


# ─── Private helpers ──────────────────────────────────────────────────────────


def _clean(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    s = re.sub(r"\s+", " ", s)  # collapse multiple spaces
    return s if s and s.lower() not in ("nan", "none", "") else None


def _strip_suffix(name: str) -> str:
    return _ROLE_SUFFIX.sub("", name).strip()


def _make_key(name: str) -> str:
    """Canonical lookup key: strip role suffix, uppercase, collapse spaces."""
    return re.sub(r"\s+", " ", _strip_suffix(name)).upper().strip()
