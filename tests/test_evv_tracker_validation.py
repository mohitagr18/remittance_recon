"""
tests/test_evv_tracker_validation.py
EVV Tracker Validation Suite — compares Excel tracker vs DuckDB live data.
Can be run as:
  python -m pytest tests/test_evv_tracker_validation.py -v
Or called programmatically from the Streamlit Data Management UI.
"""
from __future__ import annotations
import re, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import pandas as pd
import duckdb

# ── helpers ────────────────────────────────────────────────────────────────────

_SUFFIX_RE = re.compile(r"\s+(LPN|RN|CNA|HHA|CHHA|NP|PA|Respite)$", re.IGNORECASE)
_TOL = 1.00  # dollar tolerance for float comparison


@dataclass
class TestResult:
    name: str
    passed: bool
    total_checks: int
    failed_checks: int
    diffs: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "total_checks": self.total_checks,
            "failed_checks": self.failed_checks,
            "diffs": self.diffs,
            "error": self.error,
        }


# ── Excel parser ───────────────────────────────────────────────────────────────

def parse_excel_tracker(path: str | Path) -> pd.DataFrame:
    """
    Parse EVV Billing Log Excel into a flat DataFrame with columns:
    sheet_name, billing_week, display_name, bill_code,
    billed_amt, paid_amt, pending_amt, status
    """
    xl = pd.read_excel(path, sheet_name=None, header=None)
    rows: list[dict] = []

    for sheet_name, df in xl.items():
        current_week = None
        for _, row in df.iterrows():
            c0 = str(row[0]).strip() if pd.notna(row[0]) else ""
            c1 = str(row[1]).strip() if pd.notna(row[1]) else ""

            # Detect week header rows (contain "/" date pattern like "01/07/26-01/13/26")
            if re.search(r"\d{2}/\d{2}/\d{2}", c0) and "-" in c0:
                current_week = c0
                continue

            # Skip structural rows
            if not c0 or c0 in ("nan", "NaN", "Billing Week", "Client") or "/" in c0:
                continue
            if c0.upper() == "TOTAL" or c0.upper().startswith("TOTAL"):
                continue
            if not c1 or c1 == "nan":
                continue

            def safe_float(v: Any) -> float:
                try:
                    return float(str(v).replace(",", "").replace("$", "").strip())
                except (ValueError, TypeError):
                    return 0.0

            rows.append({
                "sheet_name":   sheet_name,
                "billing_week": current_week or "",
                "display_name": c0,
                "bill_code":    c1,
                "billed_amt":   safe_float(row[7]) if len(row) > 7 else 0.0,
                "paid_amt":     safe_float(row[8]) if len(row) > 8 else 0.0,
                "pending_amt":  safe_float(row[9]) if len(row) > 9 else 0.0,
            })

    return pd.DataFrame(rows)


# ── Individual tests ───────────────────────────────────────────────────────────

def test_client_list(excel_df: pd.DataFrame, conn: duckdb.DuckDBPyConnection) -> TestResult:
    """Every (display_name, bill_code) in Excel should exist in skilled_tracker_clients."""
    excel_pairs = set(zip(excel_df["display_name"], excel_df["bill_code"]))
    db_pairs = set(
        conn.execute("SELECT display_name, bill_code FROM skilled_tracker_clients WHERE is_active").df()
        .apply(lambda r: (r["display_name"], r["bill_code"]), axis=1)
    )
    missing = excel_pairs - db_pairs
    extra   = db_pairs - excel_pairs

    diffs = []
    for name, code in sorted(missing):
        diffs.append({"type": "missing_from_db", "display_name": name, "bill_code": code})
    for name, code in sorted(extra):
        diffs.append({"type": "extra_in_db", "display_name": name, "bill_code": code})

    return TestResult(
        name="test_client_list",
        passed=len(diffs) == 0,
        total_checks=len(excel_pairs),
        failed_checks=len(diffs),
        diffs=diffs,
    )


def _week_str_to_dates(week_str: str) -> tuple[str, str]:
    """Convert '01/07/26-01/13/26' to ('2026-01-07', '2026-01-13')."""
    parts = week_str.split("-")
    def _parse(s: str) -> str:
        m, d, y = s.strip().split("/")
        return f"20{y}-{m.zfill(2)}-{d.zfill(2)}"
    return _parse(parts[0]), _parse(parts[1])


def _test_amounts(
    excel_df: pd.DataFrame,
    conn: duckdb.DuckDBPyConnection,
    col: str,
    test_name: str,
) -> TestResult:
    """Generic per-(client, bill_code, week) amount comparison."""
    diffs = []
    total = 0
    failed = 0

    # Resolve remittance name lookup first so we can group by remittance_name
    nm = conn.execute("SELECT display_name, remittance_name FROM skilled_tracker_clients").df()
    nm_dict = dict(zip(nm["display_name"], nm["remittance_name"]))

    # Map each Excel row to its remittance_name, then group by (remittance_name, billing_week)
    # This correctly merges LPN + RN rows that share the same remittance_name in the DB
    excel_mapped = excel_df.copy()
    excel_mapped["remittance_name"] = excel_mapped["display_name"].map(nm_dict)

    # Rows with no mapping tracked separately
    no_mapping = excel_mapped[excel_mapped["remittance_name"].isna() & (excel_mapped[col] > 0)]
    for _, nm_row in no_mapping.iterrows():
        diffs.append({
            "display_name": nm_row["display_name"], "bill_code": nm_row["bill_code"],
            "week": nm_row["billing_week"], "excel_val": float(nm_row[col]),
            "db_val": 0.0, "delta": float(nm_row[col]),
            "note": "no remittance_name mapping",
        })

    grouped = (
        excel_mapped[excel_mapped["remittance_name"].notna()]
        .groupby(["remittance_name", "billing_week"])[col]
        .sum()
        .reset_index()
    )

    for _, row in grouped.iterrows():
        excel_val = float(row[col])
        rem_name = row["remittance_name"]
        week = row["billing_week"]
        # Use first matching display_name for reporting
        display = excel_mapped[excel_mapped["remittance_name"] == rem_name]["display_name"].iloc[0]
        code = ""
        total += 1

        if not week or "/" not in week:
            continue
        try:
            ws, we = _week_str_to_dates(week)
        except Exception:
            continue

        if col == "billed_amt":
            db_val = float(conn.execute("""
                SELECT COALESCE(SUM(charge_amount), 0)
                FROM remittance
                WHERE client_name_combined = ?
                  AND first_dos BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
                  AND is_latest = TRUE
            """, [rem_name, ws, we]).fetchone()[0])
        elif col == "paid_amt":
            db_val = float(conn.execute("""
                SELECT COALESCE(SUM(payment_amount), 0)
                FROM remittance
                WHERE client_name_combined = ?
                  AND first_dos BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
                  AND is_latest = TRUE
            """, [rem_name, ws, we]).fetchone()[0])
        else:  # pending
            row_db = conn.execute("""
                SELECT COALESCE(SUM(charge_amount), 0) - COALESCE(SUM(payment_amount), 0)
                FROM remittance
                WHERE client_name_combined = ?
                  AND first_dos BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
                  AND is_latest = TRUE
            """, [rem_name, ws, we]).fetchone()[0]
            db_val = float(row_db)

        delta = abs(excel_val - db_val)
        if delta > _TOL:
            diffs.append({
                "display_name": display, "remittance_name": rem_name, "week": week,
                "excel_val": round(excel_val, 2),
                "db_val":    round(db_val, 2),
                "delta":     round(delta, 2),
            })
            failed += 1

    return TestResult(
        name=test_name,
        passed=failed == 0,
        total_checks=total,
        failed_checks=failed,
        diffs=diffs,
    )


def test_billed_amt(excel_df: pd.DataFrame, conn: duckdb.DuckDBPyConnection) -> TestResult:
    return _test_amounts(excel_df, conn, "billed_amt", "test_billed_amt_per_client_week")


def test_paid_amt(excel_df: pd.DataFrame, conn: duckdb.DuckDBPyConnection) -> TestResult:
    return _test_amounts(excel_df, conn, "paid_amt", "test_paid_amt_per_client_week")


def test_pending_amt(excel_df: pd.DataFrame, conn: duckdb.DuckDBPyConnection) -> TestResult:
    return _test_amounts(excel_df, conn, "pending_amt", "test_pending_amt_per_client_week")


def test_week_totals(excel_df: pd.DataFrame, conn: duckdb.DuckDBPyConnection) -> TestResult:
    """Check that sum across all clients per week matches."""
    diffs = []
    total = 0
    failed = 0
    for week, grp in excel_df.groupby("billing_week"):
        if not week or "/" not in week:
            continue
        try:
            ws, we = _week_str_to_dates(week)
        except Exception:
            continue
        total += 1
        excel_billed = grp["billed_amt"].sum()
        excel_paid   = grp["paid_amt"].sum()
        db_billed = float(conn.execute("""
            SELECT COALESCE(SUM(charge_amount), 0) FROM remittance
            WHERE first_dos BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
              AND is_latest = TRUE
              AND client_name_combined IN (
                  SELECT DISTINCT remittance_name FROM skilled_tracker_clients WHERE is_active
              )
        """, [ws, we]).fetchone()[0])
        db_paid = float(conn.execute("""
            SELECT COALESCE(SUM(payment_amount), 0) FROM remittance
            WHERE first_dos BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
              AND is_latest = TRUE
              AND client_name_combined IN (
                  SELECT DISTINCT remittance_name FROM skilled_tracker_clients WHERE is_active
              )
        """, [ws, we]).fetchone()[0])
        for label, ev, dv in [("billed", excel_billed, db_billed), ("paid", excel_paid, db_paid)]:
            if abs(ev - dv) > _TOL:
                diffs.append({"week": week, "metric": label,
                              "excel_val": round(ev, 2), "db_val": round(dv, 2),
                              "delta": round(abs(ev - dv), 2)})
                failed += 1
    return TestResult(
        name="test_week_totals",
        passed=failed == 0,
        total_checks=total * 2,
        failed_checks=failed,
        diffs=diffs,
    )


def test_month_totals(excel_df: pd.DataFrame, conn: duckdb.DuckDBPyConnection) -> TestResult:
    """Check monthly grand totals (billed + paid) per sheet."""
    diffs = []
    total = 0
    failed = 0
    month_map = {
        "Jan-26": (1, 2026), "Feb-26": (2, 2026), "Mar-26": (3, 2026),
        "Apr-26": (4, 2026), "May-26": (5, 2026), "Jun-26": (6, 2026),
    }
    for sheet_name, grp in excel_df.groupby("sheet_name"):
        info = month_map.get(sheet_name)
        if not info:
            continue
        mon, yr = info
        total += 1
        excel_billed = grp["billed_amt"].sum()
        excel_paid   = grp["paid_amt"].sum()
        db_billed = float(conn.execute("""
            SELECT COALESCE(SUM(charge_amount), 0) FROM remittance
            WHERE DATE_PART('month', first_dos) = ? AND DATE_PART('year', first_dos) = ?
              AND is_latest = TRUE
              AND client_name_combined IN (
                  SELECT DISTINCT remittance_name FROM skilled_tracker_clients WHERE is_active
              )
        """, [mon, yr]).fetchone()[0])
        db_paid = float(conn.execute("""
            SELECT COALESCE(SUM(payment_amount), 0) FROM remittance
            WHERE DATE_PART('month', first_dos) = ? AND DATE_PART('year', first_dos) = ?
              AND is_latest = TRUE
              AND client_name_combined IN (
                  SELECT DISTINCT remittance_name FROM skilled_tracker_clients WHERE is_active
              )
        """, [mon, yr]).fetchone()[0])
        for label, ev, dv in [("billed", excel_billed, db_billed), ("paid", excel_paid, db_paid)]:
            if abs(ev - dv) > _TOL:
                diffs.append({"sheet": sheet_name, "metric": label,
                              "excel_val": round(ev, 2), "db_val": round(dv, 2),
                              "delta": round(abs(ev - dv), 2)})
                failed += 1
    return TestResult(
        name="test_month_totals",
        passed=failed == 0,
        total_checks=total * 2,
        failed_checks=failed,
        diffs=diffs,
    )


# ── Runner (called from Streamlit or CLI) ──────────────────────────────────────

def run_all_tests(
    excel_path: str | Path,
    conn: duckdb.DuckDBPyConnection,
) -> list[TestResult]:
    try:
        excel_df = parse_excel_tracker(excel_path)
    except Exception as e:
        return [TestResult(name="parse_excel", passed=False,
                           total_checks=0, failed_checks=1, error=str(e))]

    results = []
    for fn in [
        test_client_list,
        test_billed_amt,
        test_paid_amt,
        test_pending_amt,
        test_week_totals,
        test_month_totals,
    ]:
        try:
            results.append(fn(excel_df, conn))
        except Exception as e:
            results.append(TestResult(name=fn.__name__, passed=False,
                                      total_checks=0, failed_checks=1, error=str(e)))
    return results


def results_to_df(results: list[TestResult]) -> pd.DataFrame:
    """Flat DataFrame of all diffs for CSV export."""
    rows = []
    for r in results:
        for d in r.diffs:
            rows.append({"test": r.name, **d})
    return pd.DataFrame(rows)


# ── pytest-compatible wrappers ─────────────────────────────────────────────────
import sys
from pathlib import Path as _P

_DB_PATH  = _P(__file__).parent.parent / "data" / "recon.duckdb"
_XL_PATH  = _P(__file__).parent.parent / "input" / "EVV-2026-Billing-Log-Skilled.xlsx"


def _conn():
    return duckdb.connect(str(_DB_PATH))


def _excel():
    return parse_excel_tracker(_XL_PATH)


def test_client_list_pytest():
    assert test_client_list(_excel(), _conn()).passed, "Client list mismatch"

def test_billed_amt_pytest():
    r = test_billed_amt(_excel(), _conn())
    assert r.passed, f"{r.failed_checks} billed amount mismatches:\n" + json.dumps(r.diffs[:5], indent=2)

def test_paid_amt_pytest():
    r = test_paid_amt(_excel(), _conn())
    assert r.passed, f"{r.failed_checks} paid amount mismatches:\n" + json.dumps(r.diffs[:5], indent=2)

def test_pending_amt_pytest():
    r = test_pending_amt(_excel(), _conn())
    assert r.passed, f"{r.failed_checks} pending amount mismatches:\n" + json.dumps(r.diffs[:5], indent=2)

def test_week_totals_pytest():
    r = test_week_totals(_excel(), _conn())
    assert r.passed, f"{r.failed_checks} week total mismatches:\n" + json.dumps(r.diffs[:5], indent=2)

def test_month_totals_pytest():
    r = test_month_totals(_excel(), _conn())
    assert r.passed, f"{r.failed_checks} month total mismatches:\n" + json.dumps(r.diffs[:5], indent=2)
