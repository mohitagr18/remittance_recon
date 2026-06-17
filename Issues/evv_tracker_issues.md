# EVV Tracker Issues

This document captures the current issues identified from the EVV tracker validation export and follow-up review performed on June 17, 2026. The validation export contains 353 issue rows across billed, paid, pending, weekly total, and monthly total checks.

## Validation Summary

The exported validation file shows 116 billed per-client-week issues, 101 paid per-client-week issues, 86 pending per-client-week issues, 40 week total issues, and 10 month total issues.

Several issues that were previously believed to be test regressions are instead genuine reconciliation differences between the Excel tracker and the database, while a smaller subset reflects recent weeks that are present in the tracker but not yet loaded into the database.

---

## Issue Categories

### Category 1 — Missing Database Weeks (21 billed rows, db = 0)

A set of billed issues are cases where the Excel tracker has a positive amount but the database has zero for that week. These look like missing uploads or data not yet loaded into the local database rather than calculation bugs.

| Client | Missing Weeks |
|---|---|
| BUSSA, SALVATORE LPN | 05/20/26, 05/27/26 |
| ELLIOTT, ROSEMARY LPN | 05/20/26 |
| FERGUSON, CLAIRE LPN | 02/11/26, 03/25/26, 04/01/26, 05/06/26 |
| FLEMING, Ja'QUEZ LPN | 05/20/26 |
| HANTON, SHELBI LPN | 05/20/26 |
| JACKSON, JAHDYA LPN | 05/20/26 |
| LEAL, HAELYNN LPN | 05/20/26 |
| MORAN, LISHA LPN | 05/20/26 |
| PEGRAM, SOLEIL LPN | 05/13/26, 05/20/26 |
| RIVERA, NOEL LPN | 05/20/26 |
| WILLIAMS, AIDEN LPN | 02/18/26–03/18/26 (5 consecutive weeks), 05/20/26 |

**WILLIAMS, AIDEN** has the largest contiguous gap (5 weeks Feb–Mar 2026) and needs investigation — either the payroll files for those weeks were never uploaded, or the client was discharged and the tracker has not been updated.

**FERGUSON, CLAIRE** has 4 scattered missing weeks, suggesting incomplete remittance uploads for those specific periods.

---

### Category 2 — Reversals / Negative Values in DB (2 rows)

Two rows show clearly negative DB values, indicating a credit or reversal posted in the remittance system. The Excel tracker correctly reflects the positive pending status; the discrepancy is on the DB side.

| Client | Week | Tracker Status | DB Billed | DB Paid |
|---|---|---|---|---|
| CLINE, DANNY LPN | 02/04/26–02/10/26 | Billed $8,472.90, Paid $0.00, Pending $8,472.90 | -8,472.90 | -8,472.90 |
| ROBINSON, GEORGE LPN | 02/11/26–02/17/26 | Billed $8,889.60, Paid $2,222.40, Pending $6,667.20 | -2,222.40 (billed) | -2,222.40 (paid) |

**Note:** For ROBINSON, the tracker correctly shows a partial paid amount of $2,222.40 and a pending balance of $6,667.20. The DB has the same $2,222.40 amount as a negative reversal, meaning the DB has effectively cancelled what the tracker recorded as paid.

**Action required:** Verify whether these reversals are intentional. If so, determine whether the tracker needs an explicit credit/reversal status field, or whether the pending amounts should be cleared.

---

### Category 3 — MORAN, LISHA — Systematic ~$405 DB Overage (19–20 rows)

Every week, the DB billed amount for MORAN is approximately $404–$408 higher than the tracker amount of $8,222.88. The DB consistently shows values around $8,626–$8,630.

| Week | Excel | DB | Delta |
|---|---|---|---|
| 01/07/26–01/13/26 | 8,222.88 | 8,617.77 | 394.89 |
| 01/14/26–01/20/26 | 8,222.88 | 8,628.49 | 405.61 |
| 01/28/26–02/03/26 | 8,222.88 | 5,517.34 | **2,705.54** |
| 02/25/26–03/03/26 | 8,222.88 | 5,516.12 | **2,706.76** |
| 05/20/26–05/26/26 | 8,222.88 | 0.00 | 8,222.88 (missing upload) |

Two anomalous low weeks (01/28, 02/25) show the DB at ~$5,516–$5,517, which is about $2,706 below the tracker — likely partial payment weeks.

**Hypothesis:** The DB includes a second bill code or line item not captured in the tracker. The stable ~$405 overage is too consistent to be a rounding issue.

**Action required:** Run a query against `remittance` for `client_name_combined ILIKE '%MORAN%'` grouped by `billing_week, bill_code` to identify whether a second bill code is present that the tracker does not account for.

---

### Category 4 — JACKSON, JAHDYA — Alternating LPN/RN Split (19 rows)

JACKSON shows an alternating pattern where some weeks DB = Excel + 1,335.18 and other weeks DB = 1,335.18 only (much lower than Excel). The tracker shows a flat 4,667.04 every week.

| DB Value | Difference from Excel (4,667.04) | Interpretation |
|---|---|---|
| 6,002.22 | +1,335.18 | Both LPN and secondary code paid |
| 1,335.18 | −3,331.86 | Only secondary code paid in DB |

**Hypothesis:** JACKSON has two bill codes in the remittance system (LPN S9124 and another, likely T1002). The tracker only records one combined value. This is the same multi-role pattern seen with DERRICOTT and PEGRAM, but JACKSON currently has only one row in `skilled_tracker_clients` so the grouping logic never fires.

**Action required:** Add JACKSON as a dual-row entry in `skilled_tracker_clients` (one for S9124, one for T1002) so the validation test sums both before comparing to the tracker total.

---

### Category 5 — PEGRAM, SOLEIL — LPN/RN Timing Misalignment (13 billed rows)

The grouping fix from commit `0ce4e20` is working, but the Excel tracker itself has inconsistent representation across periods:

- **Jan–Mar 2026:** Tracker shows 3,001.86 per week (combined LPN+RN), DB shows only 1,667.70 (one code paid per week). Delta = 1,334.16 consistently.
- **Apr 2026 onward:** Tracker drops to 1,667.70, while DB jumps to 3,224.22–4,336.02 (catch-up rebilling).

| Period | Tracker | DB | Pattern |
|---|---|---|---|
| Jan 21–Mar 31 | 3,001.86 | 1,667.70 | DB underpays by 1,334.16 |
| Apr 01 | 1,667.70 | 4,336.02 | DB overpays — likely rebill accumulation |
| Apr 15–Apr 22 | 1,667.70 | 3,224.22 | DB overpays — RN catch-up |

**Action required:** Confirm with billing team whether the Jan–Mar shortfalls were resolved in the April rebills. If so, these are expected reconciliation differences rather than open issues.

---

### Category 6 — FLEMING, Ja'QUEZ — Persistent Reconciliation Gap (18 billed rows)

After the name-mapping fix (commit `0ce4e20`), FLEMING is now correctly matched in the DB but shows large per-week amount differences. The DB amount is frequently 485.52 while the tracker shows 1,445–3,113.

- 485.52 appears to represent a single visit payment in remittance.
- The tracker records full weekly expected billed amounts.

This is no longer a mapping or grouping bug — it is a genuine reconciliation shortfall where the remittance system is not paying out the full weekly tracked amounts for this client.

**Action required:** Review FLEMING remittance records directly to determine whether payments are being split across different periods or bill codes not captured in the tracker.

---

### Category 7 — DREWRY, KAYLA — Mixed Discrepancies (17 billed rows)

DREWRY has the second-highest number of mismatches after MORAN/JACKSON, but unlike those clients the deltas are irregular — both DB overcounts and undercounts appear in different weeks without a clean repeating pattern.

Examples:
- 01/07/26: Excel 3,113.04, DB 374.86 (large undercount)
- 01/28/26: Excel 3,113.04, DB 3,861.55 (overcount)
- 02/11/26: Excel 0.0, DB 1,355.41 (DB has it, tracker does not)

**Action required:** Review DREWRY remittance data for possible partial uploads, delayed remittances, or cross-week payments. This client likely needs manual line-by-line reconciliation rather than a systematic fix.

---

## Weekly and Monthly Totals

The `test_week_totals` and `test_month_totals` failures are downstream effects of the per-client mismatches above. Notable outliers:

- **05/06/26–05/12/26 paid total:** Excel = 0.0, DB = 64,308.13 — entire week missing from tracker paid column
- **05/13/26–05/19/26 paid total:** Excel = 0.0, DB = 52,975.34
- **May-26 paid month total:** Excel = 0.0, DB = 164,391.95

These totals should not be addressed independently. They will self-correct once the underlying per-client billed, paid, and pending issues are resolved.

---

## Immediate Follow-up Actions

1. **Upload missing payroll files** for the 05/20/26 week across all active clients.
2. **Investigate WILLIAMS, AIDEN** Feb–Mar 2026 gap — determine if discharged or missing uploads.
3. **Investigate FERGUSON, CLAIRE** 4 scattered missing weeks.
4. **Confirm CLINE and ROBINSON reversals** — determine if tracker pending amounts should be cleared or if a credit status needs to be tracked.
5. **Add JACKSON dual-row entry** in `skilled_tracker_clients` to enable LPN+RN grouping.
6. **Run bill code query for MORAN** to identify the source of the ~$405 weekly overage.
7. **Review PEGRAM Apr rebills** with billing team to confirm Jan–Mar shortfalls were resolved.
8. **Manual review of FLEMING and DREWRY** remittance records.
