"""Tests for src/etl/reconciliation.py"""

from src.etl.reconciliation import compute_result, compute_deltas


class TestComputeResult:
    def test_no_payroll_hours(self):
        assert compute_result(0, 0, 0) == ("No Payroll Hours", None)

    def test_no_payroll_hours_with_bill(self):
        assert compute_result(0, 5, 5) == ("No Payroll Hours", None)

    def test_good_exact_match(self):
        assert compute_result(35, 35, 35) == ("Good", None)

    def test_good_within_tolerance(self):
        assert compute_result(35, 35.5, 35.5) == ("Good", None)

    def test_followup_not_billed(self):
        result, detail = compute_result(35, 0, 0)
        assert result == "Follow up"
        assert detail == "Not Billed"

    def test_followup_billed_short(self):
        result, detail = compute_result(35, 20, 20)
        assert result == "Follow up"
        assert detail == "Billed Short"

    def test_billed_extra_is_good(self):
        assert compute_result(35, 40, 40) == ("Good", None)

    def test_followup_not_paid(self):
        result, detail = compute_result(35, 35, 0)
        assert result == "Follow up"
        assert detail == "Not Paid"

    def test_followup_paid_less(self):
        result, detail = compute_result(35, 35, 20)
        assert result == "Follow up"
        assert detail == "Paid Less"

    def test_followup_paid_excess(self):
        result, detail = compute_result(35, 35, 40)
        assert result == "Follow up"
        assert detail == "Paid Excess"

    def test_copay_good_within_tolerance(self):
        result, detail = compute_result(35, 34.5, 34.5, is_copay=True)
        assert result == "Good"

    def test_copay_followup_beyond_tolerance(self):
        result, detail = compute_result(35, 20, 20, is_copay=True)
        assert result == "Follow up"

    def test_none_treated_as_zero(self):
        assert compute_result(None, None, None) == ("No Payroll Hours", None)

    def test_negative_hours_payer_reversal(self):
        assert compute_result(35, -5, 35) == ("Follow up", "Payer Reversal")
        assert compute_result(35, 35, -10) == ("Follow up", "Payer Reversal")

    def test_rebill_fully_paid_is_good(self):
        # We billed 100 but payroll is 35 and we got paid 35. Under the new logic,
        # since paid matches payroll and billed >= payroll, this is Good!
        assert compute_result(35, 100, 35) == ("Good", None)

    def test_rebill_partially_paid_short(self):
        # We billed 100 but payroll is 35 and we got paid 20. Under the new logic,
        # since paid (20) < payroll (35) - tolerance, this is Paid Less!
        assert compute_result(35, 100, 20) == ("Follow up", "Paid Less")

    def test_rebill_excess_paid(self):
        # We billed 100 but payroll is 35 and we got paid 40. Under the new logic,
        # since paid (40) > payroll (35) + tolerance, this is Paid Excess!
        assert compute_result(35, 100, 40) == ("Follow up", "Paid Excess")


class TestComputeDeltas:
    def test_exact_match(self):
        pvb, bvp, pvp = compute_deltas(35, 35, 35)
        assert pvb == 0
        assert bvp == 0
        assert pvp == 0

    def test_differences(self):
        pvb, bvp, pvp = compute_deltas(35, 30, 25)
        assert pvb == 5
        assert bvp == 5
        assert pvp == 10

    def test_none_treated_as_zero(self):
        pvb, bvp, pvp = compute_deltas(None, 10, 5)
        assert pvb == -10
        assert bvp == 5
        assert pvp == -5


class TestComputeCopayMonthlyStatus:
    """Tests for compute_copay_monthly_status() — dollar-based monthly copay logic."""

    # ── Scenario 1: Fully Paid ($0 pending) ───────────────────────────────────

    def test_fully_paid_zero_pending(self):
        """COCHRAN Jul 2025 — $0 pending, payer covered everything."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(0.00, 144.41) == ("Good", None)

    def test_fully_paid_within_tolerance(self):
        """Pending $0.50 is within ±$1 tolerance — still fully paid."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(0.50, 144.41) == ("Good", None)

    def test_fully_paid_negative_pending(self):
        """Overpayment (negative pending) — treat as Good."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        result, _ = cms(-50.00, 383.00)
        assert result == "Good"

    # ── Scenario 2: Copay Pending (pending ≈ copay) ───────────────────────────

    def test_copay_pending_exact(self):
        """BERRYMAN Jan 2026 — pending $383.00 exactly matches copay."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(383.00, 383.00) == ("Good", "Copay")

    def test_copay_pending_within_tolerance_low(self):
        """Pending $382.20 — within ±$1 of copay $383.00."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(382.20, 383.00) == ("Good", "Copay")

    def test_copay_pending_within_tolerance_high(self):
        """Pending $383.80 — within ±$1 of copay $383.00."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(383.80, 383.00) == ("Good", "Copay")

    def test_copay_pending_butler(self):
        """BUTLER, JANNIE — pending $643.59 = copay $643.59."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(643.59, 643.59) == ("Good", "Copay")

    def test_copay_pending_jarrett(self):
        """JARRETT, VICTORIA — pending $19.00 = copay $19.00."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(19.00, 19.00) == ("Good", "Copay")

    # ── Scenario 3: Exceeds Copay (pending > copay) ───────────────────────────

    def test_exceeds_copay_berryman_jun2025(self):
        """BERRYMAN Jun 2025 — pending $399 vs copay $383, excess $16."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(399.00, 383.00) == ("Follow up", "Exceeds Copay")

    def test_exceeds_copay_berryman_reversal(self):
        """BERRYMAN Jul 2025 — payer reversal, paid was -$770, pending $2,368."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(2368.28, 383.00) == ("Follow up", "Exceeds Copay")

    def test_exceeds_copay_berryman_zero_paid(self):
        """BERRYMAN May 2026 — $0 paid on $3,459 billed."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(3459.33, 383.00) == ("Follow up", "Exceeds Copay")

    def test_exceeds_copay_butts_recurring_3_dollar(self):
        """BUTTS Oct 2025-May 2026 — pending $156 vs stored copay $153.
        $3 excess flags Exceeds Copay — 8-month pattern suggests actual
        copay may be $156 (pending verification with billing team)."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(156.00, 153.00) == ("Follow up", "Exceeds Copay")

    def test_exceeds_copay_jarrett_zero_paid(self):
        """JARRETT Apr 2025 — $0 paid on $6,980 billed."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(6980.16, 19.00) == ("Follow up", "Exceeds Copay")

    def test_exceeds_copay_massenburg(self):
        """MASSENBURG Nov 2025 — pending $544.56 vs copay $397.26, excess $147."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(544.56, 397.26) == ("Follow up", "Exceeds Copay")

    def test_exceeds_copay_towers(self):
        """TOWERS Feb/Mar 2026 — pending $1,378.30 vs copay $1,176.00, excess $202.30."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(1378.30, 1176.00) == ("Follow up", "Exceeds Copay")

    # ── Partial Copay (0 < pending < copay) ───────────────────────────────────

    def test_partial_copay_berryman_mar2025(self):
        """BERRYMAN Mar 2025 — pending $37.89, copay $383.00. Underpaid vs copay."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(37.89, 383.00) == ("Follow up", "Partial Copay")

    def test_partial_copay_claiborne(self):
        """CLAIBORNE Apr 2025 — pending $401.02 vs copay $535.00."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(401.02, 535.00) == ("Follow up", "Partial Copay")

    # ── Edge cases ─────────────────────────────────────────────────────────────

    def test_no_copay_configured(self):
        """copay_amount = 0 — no copay on file, always Good."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(500.00, 0.00) == ("Good", None)

    def test_none_pending_treated_as_zero(self):
        """None pending coerced to 0.0 — fully paid."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(None, 383.00) == ("Good", None)

    def test_none_copay_treated_as_zero(self):
        """None copay_amount — treat as no copay configured."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        result, _ = cms(100.00, None)
        assert result == "Good"

    def test_boundary_just_above_tolerance(self):
        """Pending $384.01 — just outside ±$1 of copay $383.00 → Exceeds Copay."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(384.01, 383.00) == ("Follow up", "Exceeds Copay")

    def test_boundary_just_inside_tolerance(self):
        """Pending $383.99 — just inside ±$1 of copay $383.00 → Copay."""
        from src.etl.reconciliation import compute_copay_monthly_status as cms
        assert cms(383.99, 383.00) == ("Good", "Copay")
