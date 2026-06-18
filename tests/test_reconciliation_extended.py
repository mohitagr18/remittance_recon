"""
tests/test_reconciliation_extended.py
Extended tests for src/etl/reconciliation.py covering scenarios
NOT yet present in test_reconciliation.py.

Adds:
  - NaN float inputs treated as zero
  - Exact tolerance boundary (pvb=0.9 -> Good, pvb=0.91 -> Follow up)
  - Billing Error classification (0.01 < bvp <= tolerance)
  - compute_deltas with all-zero and partial-None inputs
  - compute_copay_monthly_status boundary precision cases
  - _safe() internal helper via public API
"""
from __future__ import annotations
import math

import pytest

from src.etl.reconciliation import (
    compute_result,
    compute_deltas,
    compute_copay_monthly_status as cms,
    TOLERANCE,
    COPAY_DOLLAR_TOLERANCE,
)


class TestComputeResultExtended:
    # ── NaN handling ──────────────────────────────────────────────────────────
    def test_nan_payroll_treated_as_zero(self):
        """NaN payroll -> No Payroll Hours (same as 0)."""
        assert compute_result(float("nan"), 35, 35) == ("No Payroll Hours", None)

    def test_nan_billed_treated_as_zero(self):
        """NaN billed -> Not Billed (billed < 1)."""
        r, d = compute_result(35, float("nan"), 0)
        assert r == "Follow up"
        assert d == "Not Billed"

    def test_nan_paid_treated_as_zero(self):
        """NaN paid with good payroll/billed -> Not Paid."""
        r, d = compute_result(35, 35, float("nan"))
        assert r == "Follow up"
        assert d == "Not Paid"

    # ── Tolerance boundary precision ──────────────────────────────────────────
    def test_tolerance_exact_boundary_is_good(self):
        """Delta exactly == TOLERANCE (0.9) on both axes -> Good."""
        assert compute_result(35, 35 + TOLERANCE, 35 + TOLERANCE) == ("Good", None)

    def test_pvb_just_over_tolerance_and_pvp_exceeds(self):
        """pvb AND pvp both exceed tolerance -> Follow up (not Good)."""
        # payroll=35, billed=37, paid=33: pvb=-2>tol, pvp=2>tol, billed_short? 37<34.1? No
        # paid<1? No. paid=33<34.1? YES → Paid Less
        r, d = compute_result(35, 37, 33)
        assert r == "Follow up", f"Expected Follow up, got {r}"

    def test_bvp_exactly_zero_point_nine_is_good(self):
        """billing_vs_paid = 0.9 (exactly at threshold) -> Good."""
        assert compute_result(35, 35, 35 - TOLERANCE) == ("Good", None)

    # ── Billing Error path ────────────────────────────────────────────────────
    def test_billing_error_bvp_within_tolerance(self):
        """Billing Error fires when pvb>tol, pvp>tol, and 0.01<bvp<=tol."""
        # payroll=35, billed=38, paid=37.5
        # pvb = 35-38 = -3 (abs > 0.9) → Good check fails
        # pvp = abs(35-37.5) = 2.5 (abs > 0.9) → pvp-Good check fails
        # billed_short? 38 < 34.1? No. paid<1? No. paid_less? 37.5<34.1? No
        # paid_excess? 37.5>35.9 AND bvp=0.5>0.9? No → Billing Error: 0.01<0.5<=0.9
        r, d = compute_result(35, 38, 37.5)
        assert r == "Follow up"
        assert d == "Billing Error"

    # ── All-zero corner case ──────────────────────────────────────────────────
    def test_all_zeros_no_payroll(self):
        """0, 0, 0 -> No Payroll Hours."""
        assert compute_result(0, 0, 0) == ("No Payroll Hours", None)

    # ── Copay flag no effect on No Payroll Hours ──────────────────────────────
    def test_copay_flag_no_payroll_still_no_payroll(self):
        """is_copay=True with payroll=0 -> No Payroll Hours (copay flag irrelevant)."""
        assert compute_result(0, 0, 0, is_copay=True) == ("No Payroll Hours", None)


class TestComputeDeltasExtended:
    def test_all_zeros(self):
        assert compute_deltas(0, 0, 0) == (0.0, 0.0, 0.0)

    def test_none_payroll(self):
        pvb, bvp, pvp = compute_deltas(None, 10, 5)
        assert pvb == -10.0
        assert bvp ==   5.0
        assert pvp ==  -5.0

    def test_all_none(self):
        assert compute_deltas(None, None, None) == (0.0, 0.0, 0.0)

    def test_rounding_to_4_decimal_places(self):
        """Values are rounded to 4 decimal places."""
        pvb, bvp, pvp = compute_deltas(35.12345, 35.12341, 35.12341)
        assert pvb == round(35.12345 - 35.12341, 4)


class TestCopayMonthlyStatusExtended:
    """Boundary precision tests not covered in test_reconciliation.py."""

    # ── Exact $1.00 boundary: fully-paid zone ────────────────────────────────
    def test_pending_exactly_one_dollar_is_fully_paid(self):
        """pending = COPAY_DOLLAR_TOLERANCE exactly -> Good / None."""
        assert cms(COPAY_DOLLAR_TOLERANCE, 383.00) == ("Good", None)

    def test_pending_one_cent_over_tolerance_is_not_fully_paid(self):
        """pending = $1.01 when copay=$383 -> Follow up (Partial Copay)."""
        r, note = cms(1.01, 383.00)
        assert r == "Follow up"
        assert note == "Partial Copay"

    # ── Exact $1.00 boundary: copay zone ─────────────────────────────────────
    def test_pending_exactly_copay_plus_tolerance_is_still_copay(self):
        """pending = copay + $1.00 exactly -> Good / Copay (within tolerance)."""
        assert cms(383.00 + COPAY_DOLLAR_TOLERANCE, 383.00) == ("Good", "Copay")

    def test_pending_one_cent_over_copay_tolerance_exceeds(self):
        """pending = copay + $1.01 -> Follow up / Exceeds Copay."""
        r, note = cms(383.00 + COPAY_DOLLAR_TOLERANCE + 0.01, 383.00)
        assert r == "Follow up"
        assert note == "Exceeds Copay"

    # ── Zero copay short-circuits everything ──────────────────────────────────
    def test_zero_copay_any_pending_is_good(self):
        """copay_amount=0 -> always Good regardless of pending."""
        assert cms(9999.00, 0.00) == ("Good", None)

    def test_negative_copay_is_good(self):
        """Negative copay_amount treated same as 0 -> Good."""
        r, _ = cms(100.00, -50.00)
        assert r == "Good"

    # ── Large realistic values ────────────────────────────────────────────────
    def test_towers_exceeds_copay(self):
        """TOWERS: pending $1,378.30 vs copay $1,176.00 -> Exceeds Copay."""
        assert cms(1378.30, 1176.00) == ("Follow up", "Exceeds Copay")

    def test_butler_copay_match(self):
        """BUTLER: pending $643.59 = copay $643.59 -> Good / Copay."""
        assert cms(643.59, 643.59) == ("Good", "Copay")
