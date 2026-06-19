"""
src/etl/seed_tracker.py
Seed skilled_tracker_clients from the Excel EVV Billing Log.
Run once (or re-run idempotently) to bootstrap bill code mappings.
"""
from __future__ import annotations
import re, sys
from pathlib import Path
import pandas as pd
import duckdb

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import cfg

_SUFFIX_RE = re.compile(
    r"\s+(LPN|RN|CNA|HHA|CHHA|NP|PA|Respite)$", re.IGNORECASE
)

def _service_type(name: str) -> str:
    m = _SUFFIX_RE.search(name)
    return m.group(1).title() if m else "LPN"

def _base_name(name: str) -> str:
    """Strip role suffix to get lookup name for name_match table."""
    return _SUFFIX_RE.sub("", name).strip()

def seed_from_excel(excel_path: str | Path, conn: duckdb.DuckDBPyConnection) -> int:
    """Parse Excel tracker, upsert all (display_name, bill_code) pairs. Returns rows inserted."""
    xl = pd.read_excel(excel_path, sheet_name=None, header=None)
    pairs: dict[tuple[str, str], str] = {}  # (display_name, bill_code) -> service_type

    for sheet_df in xl.values():
        for _, row in sheet_df.iterrows():
            cell0 = str(row[0]).strip() if pd.notna(row[0]) else ""
            bill_code = str(row[1]).strip() if pd.notna(row[1]) else ""
            if (not cell0 or cell0 in ("nan", "NaN", "Billing Week", "Total")
                    or "/" in cell0 or not bill_code or bill_code == "nan"):
                continue
            key = (cell0, bill_code)
            if key not in pairs:
                pairs[key] = _service_type(cell0)

    # Build name_match lookup (payroll_name -> remittance_name)
    nm = conn.execute("SELECT payroll_name, remittance_name FROM name_match").df()
    nm_dict: dict[str, str] = dict(zip(nm["payroll_name"], nm["remittance_name"]))

    # Also build a base-name lookup
    nm_base: dict[str, str] = {}
    for pname, rname in nm_dict.items():
        base = _base_name(pname)
        if base not in nm_base and rname:
            nm_base[base] = rname

    inserted = 0
    for (display_name, bill_code), svc in pairs.items():
        # Try exact match first, then base name
        rem_name = nm_dict.get(display_name) or nm_base.get(_base_name(display_name))
        try:
            conn.execute("""
                INSERT INTO skilled_tracker_clients
                    (id, display_name, bill_code, service_type, remittance_name, is_active)
                VALUES (nextval('seq_skilled_tracker_clients'), ?, ?, ?, ?, TRUE)
                ON CONFLICT (display_name, bill_code) DO UPDATE SET
                    service_type    = excluded.service_type,
                    remittance_name = COALESCE(excluded.remittance_name, skilled_tracker_clients.remittance_name),
                    is_active       = TRUE
            """, [display_name, bill_code, svc, rem_name])
            inserted += 1
        except Exception as e:
            print(f"  Skipped {display_name}/{bill_code}: {e}")

    return inserted


if __name__ == "__main__":
    excel = sys.argv[1] if len(sys.argv) > 1 else str(cfg.input_dir / "master_remit" / "EVV-2026-Billing-Log-Skilled.xlsx")
    conn = duckdb.connect(str(cfg.db_path))
    from src.db.schema import create_all
    create_all(conn)
    n = seed_from_excel(excel, conn)
    conn.close()
    print(f"Seeded {n} client/bill-code pairs into skilled_tracker_clients")
