# Pending Items

Things deferred for future implementation.

---

## EVV Tracker
- Multiple entries for Derricott and Pegram on the heatmap. Some are wrong

## Copay: Partial Client Copay Tracking

**Context:** The Copay Manager currently assumes client copay is always paid in full.
All status logic and shortfall calculations are built on that assumption.

**What to add later:**
A separate tracking mechanism for cases where clients only partially pay their copay.
This would require:
- A way to record actual client copay payments (separate from remittance)
- A new status / section on the Copay Manager for "Copay Partially Collected"
- Shortfall split into two buckets: insurance shortfall vs. client copay shortfall

**Why deferred:** Low priority relative to insurance follow-up workflow.
The current model (copay always assumed collected) is correct for the primary use case.
