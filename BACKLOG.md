# Backlog

Items noted for future work, not yet scheduled.

---

## Unskilled Tracker

### 1. Copay Management & Reconciliation Logic
**Priority:** Medium  
**Area:** Unskilled Tracker · ETL / Reconciliation

**Context:**  
Some unskilled clients (e.g. Micah Richey) have a fixed monthly copay amount. These copay
amounts rarely change — once set they stay unless manually updated.

**Requirements:**

#### Data / Schema
- Add a `unskilled_copay` table (or extend existing copay mechanism) with:
  - `client_name` (display name or linked ID)
  - `copay_amount` (monthly dollar amount)
  - `effective_from` date — allows point-in-time lookup if amount ever changes
  - `updated_at` timestamp
- Support multiple historical copay entries per client

#### UI — Copay Management Page / Panel
- CRUD interface: add / update / delete a client's copay amount
- Accessible from the Unskilled Tracker or Settings page
- Show current copay and effective date; allow inline editing
- Copay amounts are monthly, not weekly

#### Reconciliation Logic Change
For copay clients, update dollar-based status logic:
- `pending ≈ copay_amount (± small tolerance)` → **Good** (pending IS the expected copay)
- `pending > copay_amount` → **Follow Up / Pending Exceeds Copay** (overage beyond copay needs review)
- `pending == 0` → **Good** (fully paid, including copay)

**Timing note:** Copay amounts are usually applied beginning to mid-month — aggregate
pending across the month before comparing to the copay threshold.

#### Notes
- The existing `is_copay` boolean flag in `reconciliation.py` handles hours-based tolerance —
  keep it. This new logic adds a separate dollar-amount check on top.
- Pipeline needs to look up the effective copay for each client × month when computing status.

---

## Skilled Tracker

*(No items yet)*

---

## General / Infrastructure

*(No items yet)*
