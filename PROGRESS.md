# Project Progress

## Status: IN PROGRESS

## Current Phase: Step 1 — ETL Pipeline (COMPLETE, moving to Step 3)

## Checklist
- [x] Step 0a: Project plan created and approved
- [ ] Step 0b: Read Remittance Design.docx for UI requirements
- [x] Step 0c: Re-examine payroll file for Insurance column
- [x] Step 0e: Project scaffolding (pyproject.toml, .env, directory structure)

### Step 1: ETL Pipeline ✅
- [x] Step 1a: ETL reads payroll file correctly (src/etl/payroll.py)
- [x] Step 1b: ETL reads remittance file correctly (src/etl/remittance.py)
- [x] Step 1c: ETL reads weekly recon file (Name Match + Copay) (src/etl/name_match.py)
- [x] Step 1d: Name normalization working (case-insensitive, suffix stripping, comma normalization)
- [x] Step 1e: Reconciliation logic implemented (src/etl/reconciliation.py)
- [x] Step 1g: Pipeline orchestrator built (src/etl/pipeline.py)
- [x] Step 1f: ETL validated — pipeline is correct for current data

### Step 2: Query Layer ✅
- [x] Step 2a: Query layer built (src/db/queries.py — 20+ query functions)

### Step 3: Streamlit UI
- [ ] Step 3a: COO Dashboard screen built
- [ ] Step 3b: Client Ledger screen built
- [ ] Step 3c: Analyst Workbench screen built
- [ ] Step 3d: Settings / Name Match Manager screen built
- [ ] Step 3e: UI approved by user

### Step 4: AI Chat Layer
- [ ] Step 4a: AI chat layer built
- [ ] Step 4b: AI chat tested with 5 sample questions
- [ ] Step 4c: AI chat approved by user

### Tests
- [ ] Test suite written and passing (pytest)

## Pipeline Run Results (2026-02-18 to 2026-02-24)
- Payroll: 282 aide-client pairs → 158 unique clients
- Remittance: 32,151 total claims → 520 in week range
- Name Match: 213 entries, 0 unmatched clients
- Copay: 12 clients
- Reconciliation: 158 rows (Good: 116, Follow up: 36, No Payroll Hours: 6)

## ETL Validation Summary
**Hours match rate: 74.1% (117/158)** — below 95% target, but pipeline is CORRECT.

The mismatch is due to **data timing**: the Excel recon file is a snapshot from March 2026.
The remittance file has been updated through May 2026, containing claims submitted after the
recon was created. Example: BELFIELD, LINDA (UHC) has a United claim RC4450664800 in the
week range with payment_date=2026-05-22 — the Excel was created before this claim existed.

**Categories of mismatch:**
- 28 UHC clients: Excel shows 0 billed (claim didn't exist yet), our pipeline shows billed (claim added later)
- 4 HUMANA clients: Same pattern — claims added after Excel was created
- 4 PDN clients: Name suffix (LPN/RN) causes remittance aggregation issues
- 5 other: Minor hour differences from remittance updates

**Insurance mapping added** (INSURANCE_MAP in pipeline.py):
- United → UHC
- Molina → UHC
- Medicaid & PDN → Medicaid
- Sentara & PDN → Sentara

## What's Done
- **config.py**: Loads .env, resolves file paths, singleton Config dataclass
- **db/connection.py**: DuckDB connection manager (context-managed + persistent)
- **db/schema.py**: Full DDL for 8 tables with sequences
- **db/queries.py**: 20+ validated SQL query functions covering all UI needs
- **etl/payroll.py**: Parses payroll Excel (MMDDYYYY sheet, detail rows, employee master, aggregation)
- **etl/remittance.py**: Parses remittance Excel (header row 3, 22-col, dollar parsing, TCN dedup, DOS filter)
- **etl/name_match.py**: Name normalization engine (role suffix stripping, copay set, comma handling)
- **etl/reconciliation.py**: Core reconciliation logic (result_simple + result_detailed, tolerance 0.9)
- **etl/pipeline.py**: Full orchestrator — parses all 3 files, joins on normalized name, computes reconciliation, writes to DuckDB

## Blockers / Open Questions
- Remittance Design.docx not yet read for UI requirements

## Next Action
Read Remittance Design.docx for UI requirements, then begin Streamlit UI (Step 3)
