"""
src/etl/reconciliation.py
Core reconciliation engine.

Given payroll hours, billed hours, paid hours for a client/week,
compute result_simple and result_detailed.

Logic reverse-engineered from the Excel formulas in the recon file:

  result_simple:
    - payroll == 0 AND billed == 0         → "No Payroll Hours"
    - payroll_vs_billed == 0               )
      AND billing_vs_paid == 0             → "Good"
      (within tolerance of 0.9)            )
    - else                                 → "Follow up"

  result_detailed (only when result_simple == "Follow up"):
    - billed < 1                           → "Not Billed"
    - billed < payroll                     → "Billed Short"
    - billed > payroll                     → "Billed Extra"
    - billed >= payroll AND paid < 1       → "Not Paid"
    - billed >= payroll AND paid < payroll → "Paid Less"
    - billing_vs_paid != 0 (rounding)     → "Billing Error"
    - paid > billed                        → "Paid Excess"

Note: The Excel formula uses payroll_vs_paid threshold of 0.9 (not 0.1) as
the boundary between "Good" and "Follow up" on the payroll-vs-paid column.
We preserve that tolerance here.
"""

from __future__ import annotations

_TOLERANCE = 0.9


def compute_result(
    payroll_hrs: float,
    billed_hrs: float,
    paid_hrs: float,
    is_copay: bool = False,
    tolerance: float = _TOLERANCE,
) -> tuple[str, str | None]:
    """
    Returns (result_simple, result_detailed).
    result_detailed is None when result_simple != 'Follow up'.
    """
    payroll_hrs = _safe(payroll_hrs)
    billed_hrs = _safe(billed_hrs)
    paid_hrs = _safe(paid_hrs)

    pvb = round(payroll_hrs - billed_hrs, 4)   # Payroll vs Billed
    bvp = round(billed_hrs - paid_hrs, 4)       # Billing vs Paid

    # No payroll hours — fires when payroll is 0, regardless of billed amount
    if payroll_hrs == 0:
        return "No Payroll Hours", None

    # Copay clients: within tolerance on both axes → Good
    if is_copay and abs(pvb) <= tolerance and abs(bvp) <= tolerance:
        return "Good", None

    # Good: all deltas within tolerance (mirrors Excel 0.9 threshold)
    if abs(pvb) <= tolerance and abs(bvp) <= tolerance:
        return "Good", None

    # ── Follow-up classification ──────────────────────────────────────────────
    if billed_hrs < 1:
        return "Follow up", "Not Billed"
    if billed_hrs < payroll_hrs - tolerance:
        return "Follow up", "Billed Short"
    if billed_hrs > payroll_hrs + tolerance:
        return "Follow up", "Billed Extra"

    # billed ≈ payroll from here on
    if paid_hrs < 1:
        return "Follow up", "Not Paid"
    if paid_hrs < billed_hrs - tolerance:
        return "Follow up", "Paid Less"
    if paid_hrs > billed_hrs + tolerance:
        return "Follow up", "Paid Excess"
    # Small rounding difference — classify as Billing Error, not Paid Excess
    if abs(bvp) > 0.01:
        return "Follow up", "Billing Error"

    return "Good", None


def compute_deltas(
    payroll_hrs: float,
    billed_hrs: float,
    paid_hrs: float,
) -> tuple[float, float, float]:
    """Return (payroll_vs_billed, billing_vs_paid, payroll_vs_paid)."""
    p = _safe(payroll_hrs)
    b = _safe(billed_hrs)
    d = _safe(paid_hrs)
    return (
        round(p - b, 4),
        round(b - d, 4),
        round(p - d, 4),
    )


def _safe(v) -> float:
    if v is None:
        return 0.0
    try:
        f = float(v)
        return 0.0 if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return 0.0
