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

---

## Special Case: Payer Reversal Rate Mismatch Error

### Description
A major data discrepancy occurs when the payer (insurance company) reverses a previous skilled payment (e.g. LPN care at `$53.96/hr`) but mistakenly applies the **unskilled/PCA rate** (e.g. `$19.83/hr`) to compute the hours reversed on the claim line. This results in the remittance file containing an artificially inflated negative hours value (e.g. `-130.6` hours instead of `-48.0` hours) for the reversal, leading to negative weekly paid hour totals and incorrect dashboards.

### Case Study: Soleil Pegram (DOS 2025-06-11)
* **Original Skilled Claim (TCN 25178E0025330)**:
  * Paid Amount: **$2590.08**
  * Paid Hours: **48.0**
  * Hourly Rate: $$\frac{\$2590.08}{48.0} = \$53.96\text{ / hr}$$ (Skilled LPN rate)
* **Reversal Claim (TCN 25178E0025330R1)**:
  * Reversed Amount: **-$2590.08**
  * Reversed Hours in Remittance: **-130.61**
  * Hourly Rate of Reversal: $$\frac{-\$2590.08}{-130.61} = \$19.83\text{ / hr}$$ (Unskilled PCA rate)
* **The Root Cause**: The payer divided the skilled dollar amount (`-$2590.08`) by the unskilled rate (`$19.83`) instead of the skilled rate (`$53.96`) when generating the remittance claim line:
  $$\text{Reversal Hours} = \frac{-2590.08}{19.8322} = -130.6\text{ hours}$$

---

## Proposed Clean Resolution Strategies

### Strategy A: Automated Pipeline Correction (Recommended)
During the ETL ingestion pipeline (inside `remittance.py` or `pipeline.py`), detect reversal lines where the hourly rate diverges from the client's care type contract:
1. Identify reversal records (where TCN contains suffix `R1`, `R2`, `A1` etc., and hours/amounts are negative).
2. Strip the suffix to find the original parent TCN (e.g., `25178E0025330R1` $\rightarrow$ `25178E0025330`).
3. Look up the original claim in the database and compute its rate: $$\text{Original Rate} = \frac{\text{Original Paid Amount}}{\text{Original Paid Hours}}$$
4. If a rate difference is detected, recalculate the reversal hours:
   $$\text{Adjusted Reversal Hours} = \frac{\text{Reversal Payment Amount}}{\text{Original Rate}}$$
5. Save the adjusted hours into the database. This corrects the source data immediately, ensuring all dashboards, summaries, and ledgers automatically reflect the true hourly totals.

### Strategy B: Workbench Warning Flag
Highlight rows in the Client Ledger and Analyst Workbench with a warning indicator (e.g., ⚠️) and a tool-tip when a rate mismatch is detected (where $$\left|\frac{\text{payment\_amount}}{\text{paid\_hours}} - \text{standard\_rate}\right| > 0.10$$), notifying analysts of a payer system formatting error.

