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
