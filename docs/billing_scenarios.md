# Complex Billing and Reconciliation Scenarios

This document outlines the key billing and reconciliation scenarios encountered in the remittance reconciliation system. These scenarios represent critical business rules and serve as the specification for how the reconciliation engine should calculate unique billed hours, paid hours, and pending hours when dealing with resubmissions, partial payments, voids, and payer reversals.

---

## Scenario 1: Straightforward Underpayment

### Description
The initial billing matches the payroll hours, but the insurance company pays less than the billed amount.

### Case Details
* **Payroll Hours**: 56 hrs
* **Claim History**:
  1. **TCN 1**: Bill 56 hrs $\rightarrow$ Paid 40 hrs
* **Expected Metrics**:
  * **Payroll Hours**: 56.0
  * **Billed Hours**: 56.0 (Matches Payroll)
  * **Paid Hours**: 40.0
  * **Pending Hours**: 16.0 (56.0 - 40.0)
  * **Status**: Follow-up: Paid Less

---

## Scenario 2: Incremental Billing (Different Hours)

### Description
The payroll has 56 hours. The billing team submits claims for different sub-portions of those hours at different times to eventually collect the full amount. None of the billing attempts overlap or double-bill the same hours.

### Case Details
* **Payroll Hours**: 56 hrs
* **Claim History**:
  1. **TCN 1**: Bill 56 hrs $\rightarrow$ Paid 10 hrs (46 hrs remain unpaid)
  2. **TCN 2**: Bill remaining 46 hrs $\rightarrow$ Paid 20 hrs (26 hrs remain unpaid)
  3. **TCN 3**: Rebill 25 hrs (missing 1 hr) $\rightarrow$ Paid 5 hrs (21 hrs remain unpaid + 1 hr unbilled)
  4. **TCN 4**: Rebill 26 hrs $\rightarrow$ Paid 26 hrs
* **Expected Metrics**:
  * **Payroll Hours**: 56.0
  * **Billed Hours**: 56.0 (Calculated as the total unique hours billed across the incremental sequence, which is capped at/represents the 56.0 distinct hours)
  * **Paid Hours**: 61.0 (10 + 20 + 5 + 26)
  * **Pending Hours**: 0.0 (Since paid 61.0 > payroll 56.0, we are fully paid with an excess of 5.0 hours)
  * **Status**: Good (Overpaid / Paid Excess)

---

## Scenario 3: Repetitive Full/Partial Rebilling (Same Hours)

### Description
The payroll has 56 hours. Due to denials or partial payments, the billing team resubmits claims that duplicate the *same* hours (e.g., resubmitting the entire 56 hours multiple times or rebilling a subset repeatedly) to collect the balance. Billed hours must NOT be aggregated across these resubmissions, otherwise they will artificially balloon.

### Case Details
* **Payroll Hours**: 56 hrs
* **Claim History**:
  1. **TCN 1**: Bill 56 hrs $\rightarrow$ Paid 10 hrs
  2. **TCN 2**: Bill 56 hrs (Resubmission) $\rightarrow$ Paid 20 hrs
  3. **TCN 3**: Rebill 26 hrs (Resubmission of unpaid portion) $\rightarrow$ Paid 5 hrs
  4. **TCN 4**: Bill 56 hrs (Resubmission) $\rightarrow$ Paid 21 hrs
* **Expected Metrics**:
  * **Payroll Hours**: 56.0
  * **Billed Hours**: 56.0 (The unique billed hours represent the maximum coverage of the work, which is 56.0. We should NOT sum 56 + 56 + 26 + 56 = 194.0 hrs)
  * **Paid Hours**: 56.0 (10 + 20 + 5 + 21 = 56.0)
  * **Pending Hours**: 0.0 (56.0 payroll - 56.0 paid = 0.0)
  * **Status**: Good

---

## Scenario 4: Reversal / Void & Re-bill

### Description
The billing team bills the hours and gets paid, but then voids the entire claim. The payer reverses the payment (payment goes to negative, and billed hours are adjusted). This resets the "billed/paid" bucket back to zero, allowing the team to start fresh and rebill the 56 hours.

### Case Details
* **Payroll Hours**: 56 hrs
* **Claim History**:
  1. **TCN 1**: Bill 56 hrs $\rightarrow$ Paid 10 hrs
  2. **TCN 1 Reversal (or Void)**: Bill -56 hrs $\rightarrow$ Paid -10 hrs
  3. **TCN 2**: Rebill 26 hrs $\rightarrow$ Paid 5 hrs
  4. **TCN 3**: Rebill 56 hrs $\rightarrow$ Paid 21 hrs
* **Expected Metrics**:
  * **Payroll Hours**: 56.0
  * **Billed Hours**: 56.0 (After the void/reversal, the cumulative unique billed hours reflect the final state: TCN 2 and TCN 3 representing the active billing of 56.0 hours)
  * **Paid Hours**: 26.0 (10 - 10 + 5 + 21)
  * **Pending Hours**: 30.0 (56.0 payroll - 26.0 paid)
  * **Status**: Follow-up: Paid Less

---

## Scenario 5: Overpayment (Double Payment)

### Description
The billing team bills the hours, gets paid partially, then resubmits the full claim and gets paid in full again, resulting in an overpayment.

### Case Details
* **Payroll Hours**: 56 hrs
* **Claim History**:
  1. **TCN 1**: Bill 56 hrs $\rightarrow$ Paid 10 hrs
  2. **TCN 2**: Bill 56 hrs (Resubmission) $\rightarrow$ Paid 56 hrs
* **Expected Metrics**:
  * **Payroll Hours**: 56.0
  * **Billed Hours**: 56.0 (Unique billed hours are 56.0, not 112.0)
  * **Paid Hours**: 66.0 (10 + 56)
  * **Pending Hours**: 0.0
  * **Status**: Good (Overpaid / Paid Excess)

---

## Scenario 6: Reversal After Partial Payment

### Description
The billing team bills 56 hours and gets paid 40 hours. They rebill the remaining 16 hours multiple times but get paid 0. Months later, the insurance company takes back the initial 40 hours. The payroll hours (what was paid to the caregiver) never change, but now the outstanding pending hours increase back to 56.

### Case Details
* **Payroll Hours**: 56 hrs
* **Claim History**:
  1. **TCN 1**: Bill 56 hrs $\rightarrow$ Paid 40 hrs
  2. **TCN 2**: Rebill 16 hrs $\rightarrow$ Paid 0 hrs
  3. **TCN 3**: Rebill 16 hrs $\rightarrow$ Paid 0 hrs
  4. **TCN 1 Reversal**: Bill -56 hrs $\rightarrow$ Paid -40 hrs (or a new adjustment TCN taking back 40 hrs)
* **Expected Metrics**:
  * **Payroll Hours**: 56.0
  * **Billed Hours**: 56.0 (The unique billed hours remain 56.0)
  * **Paid Hours**: 0.0 (40 - 40)
  * **Pending Hours**: 56.0 (56.0 payroll - 0.0 paid)
  * **Status**: Follow-up: Not Paid
