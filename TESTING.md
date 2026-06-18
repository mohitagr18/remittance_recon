# Testing Guide — Remittance Reconciliation System

> **Last updated:** June 2026  
> **Test framework:** pytest  
> **Total tests:** 566 across 18 test files  
> **Run command:** `pytest` (all tests) or see per-tier commands below

---

## Quick Reference — What to Run and When

| Trigger | Command | Time | Who |
|---------|---------|------|-----|
| Every code change (fast check) | `pytest tests/ -m "not live"` | ~3s | Any developer |
| Before merging a PR | `pytest tests/` (full suite) | ~10s | Developer / CI |
| After inserting new Excel files | `pytest tests/test_pipeline.py tests/test_pipeline_extended.py` | ~5s | Data operator |
| After changing reconciliation logic | `pytest tests/test_reconciliation.py tests/test_reconciliation_extended.py` | ~1s | Developer |
| After changing DB schema | `pytest tests/test_schema.py tests/test_queries.py tests/test_queries_extended.py` | ~2s | Developer |
| After changing name/copay mapping | `pytest tests/test_name_match.py tests/test_name_match_extended.py` | ~1s | Developer |

---

## The Two Test Tiers

### Tier 1 — Unit / Synthetic Tests (No real files needed)
These run anywhere — local machine, CI, fresh clone — because they build
all fixtures in-memory using `openpyxl` and `duckdb.connect(":memory:")`.
**Run these after every code change.**

### Tier 2 — Live Integration Tests (Need real Excel files)
These import `src.config.cfg` and point at the actual payroll, remittance, and
weekly recon Excel files on disk. They will **skip or fail** in environments
where those files are absent. **Run these after inserting new data files.**

---

## All Test Files — Full Catalogue

### `tests/test_reconciliation.py`  *(original — Tier 1)*
**Module:** `src/etl/reconciliation.py`  
**What it tests:** The core business-logic engine that classifies every
client-week as Good, Follow up, No Payroll Hours, or Payer Reversal.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestComputeResult` | 18 | Happy paths, all result classifications, copay flag |
| `TestComputeDeltas` | 6 | Delta calculation (pvb, bvp, pvp) |
| `TestComputeCopayMonthlyStatus` | 12 | Dollar-based copay reconciliation |
| `TestCopayEdgeCases` | 8 | Zero copay, very large copay, partial/exact/excess |
| *(top-level)* | 40 | `test_good_*`, `test_followup_*`, `test_no_payroll_*`, `test_rebill_*` |

**Run when:** Any change to `src/etl/reconciliation.py`, TOLERANCE constant, or billing scenarios.

---

### `tests/test_reconciliation_extended.py`  *(new — Tier 1)*
**Module:** `src/etl/reconciliation.py`  
**What it tests:** Edge cases not covered by the original file.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestComputeResultExtended` | 9 | NaN inputs on all 3 axes, tolerance boundary precision, Billing Error path |
| `TestComputeDeltasExtended` | 4 | All-zero, all-None, None payroll, rounding to 4dp |
| `TestCopayMonthlyStatusExtended` | 8 | $1.00 boundary precision, zero/negative copay, real client scenarios |

**Run when:** Same as `test_reconciliation.py`.

---

### `tests/test_payroll_parser.py`  *(original — Tier 2)*
**Module:** `src/etl/payroll.py`  
**What it tests:** Parsing the real payroll Excel file from `cfg.payroll_file`.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestParsePayroll` | 8 | Dates extracted, records non-empty, required fields present |
| `TestAggregatePayrollHours` | 4 | Returns list, hours positive, aggregation reduces count |

**Requires:** Real payroll Excel file at `cfg.payroll_file`.  
**Run when:** New payroll file inserted; changes to `src/etl/payroll.py`.

---

### `tests/test_payroll_parser_extended.py`  *(new — Tier 1)*
**Module:** `src/etl/payroll.py`  
**What it tests:** All structural/logic edge cases using synthetic Excel fixtures.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestPayrollNonexistentFile` | 1 | `FileNotFoundError` on missing path |
| `TestSheetDetection` | 2 | MMDDYYYY sheet found; no-digit sheet names raise `ValueError` |
| `TestFormulaRowsSkipped` | 1 | `=SUM(...)` insurance cells excluded from records |
| `TestBlankClientNameSkipped` | 1 | Rows with blank col A silently dropped |
| `TestTotalHoursComputed` | 1 | `total_hours = regular + respite`, not col G |
| `TestEmployeeIdCast` | 1 | Float `12345.0` → string `"12345"` |
| `TestRespiteBlankDefaultsZero` | 1 | `None` respite cell → `total_hours` still correct |
| `TestAggregatePayrollHoursCorrectness` | 2 | Multi-aide same client sums; different insurance separates |

**Run when:** Any change to `src/etl/payroll.py`.

---

### `tests/test_remittance_parser.py`  *(original — Tier 2)*
**Module:** `src/etl/remittance.py`  
**What it tests:** Parsing the real remittance Excel file from `cfg.remittance_file`.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestParseRemittance` | 5 | List returned, fields present, TCN dedup, `is_latest` flags |
| `TestFilterByDosRange` | 2 | Week-range filter overlaps correctly |
| `TestAggregateRemittanceHours` | 5 | Dict returned, dedup scenario, cumulative paid hours |
| `TestDetermineRemittanceCareType` | 8 | Rate-based Skilled/Unskilled, PDN insurance fallback, reversal |
| `TestCareTypeSplitAggregation` | 2 | Same client, different rates → two distinct keys |

**Requires:** Real remittance Excel file at `cfg.remittance_file`.  
**Run when:** New remittance file inserted; changes to `src/etl/remittance.py`.

---

### `tests/test_remittance_parser_extended.py`  *(new — Tier 1)*
**Module:** `src/etl/remittance.py`  
**What it tests:** Structural edge cases using synthetic Excel fixtures.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestWrongSheetRaises` | 1 | Missing `"Remittance Report Template"` sheet → `ValueError` |
| `TestShortRowsSkipped` | 1 | Rows with < 14 columns silently skipped |
| `TestDollarStringParsing` | 2 | `"$1,234.56"` → `1234.56`; plain numeric strings |
| `TestClientNameCombined` | 2 | Col 18 (`LAST, FIRST`) used; col 17 (`LAST FIRST`) not used |
| `TestBlankPaymentDefault` | 1 | Blank payment cell → `None`, no crash |
| `TestParseRemittanceIdempotent` | 1 | Two calls → identical results |

**Run when:** Any change to `src/etl/remittance.py`.

---

### `tests/test_name_match.py`  *(original — Tier 1)*
**Module:** `src/etl/name_match.py`  
**What it tests:** Name normalisation, suffix stripping, copay lookup.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestMakeKey` | 5 | Uppercase, suffix strip, space collapse |
| `TestStripSuffix` | 5 | PCA, LPN, RN, (LPN), no-suffix |
| `TestResolveClientName` | 4 | Exact match, suffix match, NOT_AVAILABLE, UNMATCHED |
| `TestIsCopayClient` | 3 | In set, in set with suffix, not in set |

**Run when:** Any change to `src/etl/name_match.py`.

---

### `tests/test_name_match_extended.py`  *(new — Tier 1)*
**Module:** `src/etl/name_match.py`  
**What it tests:** Missing-sheet fallbacks, N/A sentinel behaviour, record shapes.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestMissingNameMatchSheet` | 2 | `load_name_match` returns `{}` when sheet absent |
| `TestMissingCopaySheet` | 1 | `load_copay_clients` returns `set()` when sheet absent |
| `TestNotAvailableValues` | 4 | `None` → `NOT_AVAILABLE`; `"N/A"`/`"NA"` → `MATCHED` (documented source behaviour) |
| `TestLoadNameMatchFromExcel` | 2 | Payroll→remittance mapping; `"Not Available"` → `None` |
| `TestBuildNameMatchRecords` | 2 | Returns list of dicts with `payroll_name`/`remittance_name` |
| `TestBuildCopayRecords` | 2 | Returns list with `client_name`; empty sheet → `[]` |

**Run when:** Any change to `src/etl/name_match.py` or the Name Match / Copay sheets structure.

---

### `tests/test_file_watcher.py`  *(new — Tier 1)*
**Module:** `src/etl/file_watcher.py`  
**What it tests:** File hashing, status detection, directory scanning, archiving.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestComputeFileHash` | 4 | Consistent, distinct, 64-char hex, matches `hashlib.sha256` |
| `TestGetFileStatus` | 3 | New / Ingested (same hash) / Changed (different hash) |
| `TestScanInputDir` | 6 | Finds both file types, skips `~$` temp files, creates dirs, empty → `[]`, attributes correct, already-ingested status |
| `TestArchiveFile` | 4 | File moved, archive dir created, conflict rename, returns `Path` |

**Run when:** Any change to `src/etl/file_watcher.py`. Also run after changes to
the `ingested_files` table schema.

---

### `tests/test_pipeline.py`  *(original — Tier 2)*
**Module:** `src/etl/pipeline.py`  
**What it tests:** Full end-to-end integration using real Excel files.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestPipeline` | 15 | Full run: payroll+remittance+recon → DB rows created, KPIs non-zero |
| *(top-level)* | 5 | `test_dual_care_type_*`, `test_result_summary`, `test_unmatched_clients` |

**Requires:** All three real Excel files (`cfg.payroll_file`, `cfg.remittance_file`, `cfg.recon_file`).  
**Run when:** New files inserted; any pipeline change.

---

### `tests/test_pipeline_unit.py`  *(new — Tier 1)*
**Module:** `src/etl/pipeline.py`  
**What it tests:** All pure stateless helpers in the pipeline module.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestGetWeekStart` | 3 | 7-day parametric alignment, Wednesday identity, Tuesday rollback |
| `TestGetWeekEnd` | 2 | 6 days after start, always Tuesday |
| `TestDetermineCareType` | 9 | LPN/RN/PDN → Skilled; PCA/plain/None → Unskilled |
| `TestNormalizeInsurance` | 6 | United→UHC, PDN variants, passthrough, None |
| `TestNormalizeClientKey` | 3 | Uppercase, strip commas, collapse spaces |
| `TestDedupTcnIsLatest` | 4 | Pass 1 same-TCN, Pass 2 rebill, single record, DB state |
| `TestWritePayrollIncremental` | 1 | Same record twice → exactly 1 DB row |

**Run when:** Any change to helpers in `src/etl/pipeline.py`.

---

### `tests/test_pipeline_extended.py`  *(new — Tier 1)*
**Module:** `src/etl/pipeline.py`  
**What it tests:** Integration scenarios using synthetic Excel fixtures.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestPipelineSummaryAsDict` | 2 | All 11 keys present, defaults are 0/`[]` |
| `TestReconFileFallbackToDb` | 3 | Missing recon file → DB fallback; `load_name_match_from_db`; `load_copay_clients_from_db` |
| `TestIsTestPreventsArchive` | 1 | `archive_file` never called when `IS_TEST=True` |
| `TestPipelineHappyPath` | 2 | Synthetic files → ≥1 recon row; double-run → same count |
| `TestRateCorrectionCareType` | 1 | PDN remittance rate overrides payroll Unskilled label |

**Run when:** Any change to `run_pipeline()` or `IS_TEST` guard.

---

### `tests/test_schema.py`  *(new — Tier 1)*
**Modules:** `src/db/schema.py`, `src/db/connection.py`  
**What it tests:** Database bootstrap and connection management.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestCreateAll` | 7 | Idempotent, all 12 tables, 3 column sets, 12 sequences, migration column |
| `TestGetConn` | 3 | Yields connection, closes on exit, read-only rejects writes |
| `TestGetPersistentConn` | 2 | Creates DB file, returns open connection |

**Run when:** Any change to `src/db/schema.py`, `src/db/connection.py`, or any migration.

---

### `tests/test_queries.py`  *(original — Tier 2)*
**Module:** `src/db/queries.py`  
**What it tests:** All query functions against a database populated from real files.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestCopayMonthlyStatusQuery` | 8 | Copay status aggregation against live data |
| `TestCopayManagement` | 5 | Upsert, deactivate, history |
| *(top-level)* | 47 | `test_weekly_summary`, `test_all_reconciliation`, `test_client_ledger`, `test_rolling_trend`, etc. |

**Requires:** Populated DuckDB from a prior pipeline run.  
**Run when:** Any change to `src/db/queries.py`; after a full pipeline run.

---

### `tests/test_queries_extended.py`  *(new — Tier 1)*
**Module:** `src/db/queries.py`  
**What it tests:** Filter correctness, upsert logic, SQL injection defence, and pending hours floor.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestWeeklySummaryExtended` | 2 | KPI columns present; week filter reduces row count |
| `TestFollowupItemsExtended` | 2 | Only Follow up rows returned; `reason=` filter works |
| `TestUpsertNameMatch` | 3 | Insert new row, update existing, idempotent double-upsert |
| `TestSqlInjectionDefence` | 2 | Malicious insurance/week_start params don't corrupt DB |
| `TestClientSummaryPendingHours` | 1 | Overpayment weeks don't make `ytd_pending_hrs` go negative |

**Run when:** Any change to `src/db/queries.py`.

---

### `tests/test_evv_tracker_validation.py`  *(original — Tier 2)*
**Module:** EVV Tracker validation pipeline  
**What it tests:** EVV Billing Log validation rules.

**Requires:** Real EVV Billing Log Excel file.  
**Run when:** Changes to EVV tracker validation; new EVV file inserted.

---

### `tests/test_seed_tracker.py`  *(new — Tier 2)*
**Module:** `src/etl/seed_tracker.py`  
**What it tests:** Seeding `skilled_tracker_clients` from the EVV Billing Log.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestSeedTrackerClients` | 3 | Rows inserted, idempotent double-seed, `FileNotFoundError` on missing file |

**Requires:** Real EVV Billing Log at `cfg.evv_tracker_file` (auto-skips if absent).  
**Run when:** Changes to `src/etl/seed_tracker.py`; new EVV file.

---

### `tests/test_ai_chat.py`  *(new — Tier 1)*
**Module:** `src/ai/chat.py`  
**What it tests:** AI chat layer — all LLM calls mocked, no API keys needed.

| Class | Tests | Description |
|-------|-------|-------------|
| `TestExtractSql` | 5 | SQL fence stripping (````sql`, plain ` ``` `, whitespace, multiline) |
| `TestFormatAnswer` | 5 | Empty DataFrame, scalar, single-row, multi-row, >10 row truncation |
| `TestAsk` | 8 | Happy path, non-SELECT rejected, API exception, all keys present, fenced SQL, prompt injection, WITH clause allowed, `max_rows` cap |

**Run when:** Any change to `src/ai/chat.py`. The non-SELECT and prompt-injection
tests are **security-critical** — treat failures as P0.

---

## Test Ownership Map

| Who | Trigger | Tests to Run |
|-----|---------|-------------|
| **Developer** (any code change) | Before push | All Tier 1 files (`pytest tests/ -m "not live"`) |
| **Developer** (schema migration) | Before push | `test_schema.py` first, then full suite |
| **Developer** (reconciliation logic) | Before push | `test_reconciliation.py` + `test_reconciliation_extended.py` |
| **Data Operator** (new payroll file) | After file drop | `test_payroll_parser.py` + `test_pipeline.py` |
| **Data Operator** (new remittance file) | After file drop | `test_remittance_parser.py` + `test_pipeline.py` |
| **Data Operator** (new EVV file) | After file drop | `test_evv_tracker_validation.py` + `test_seed_tracker.py` |
| **CI/CD pipeline** | Every PR | Full suite: `pytest tests/` |

---

## Known Limitations (Document for Future Work)

The following gaps remain open — all are P1/P2 and require generating
synthetic Excel fixture files with specific structural defects:

| Gap | File to Add Test To | Why Not Done Yet |
|-----|--------------------|--------------------|
| `test_nonexistent_file_raises` | `test_payroll_parser_extended.py` | Straightforward — add now |
| `test_missing_payment_col_default_zero` | `test_remittance_parser_extended.py` | Source returns `None` not `0.0` — is a source bug to fix first |
| `test_na_na_strings_map_to_not_available` | `test_name_match_extended.py` | Source bug: `resolve_client_name` only checks `None`, not sentinel strings |
| `test_client_ledger_date_filter` | `test_queries_extended.py` | Needs populated DB with multi-month data |
| `test_rolling_trend_n_weeks` | `test_queries_extended.py` | Low value — row count assertion only |

---

---

## Operator Workflow — How Tests Actually Run

> This section is specifically for the **data operator** (the person who drops
> new Excel files and runs ingestion). No terminal required.

### The Intended Flow

Tests are **already embedded in the app**. The operator never needs to open a
terminal. Here is the full weekly cadence:

```
1. Drop new file(s)  →  input/payroll/   or   input/master_remit/
        ↓
2. Open the app  →  Admin → Data Management
        ↓
3. Tab: "📂 File Ingestion & History"
   - Scanner auto-detects files with status 🆕 New or 🔄 Changed
   - Click  🚀 Ingest New Files
        ↓
4. After ingestion completes, the app shows a green banner:
   "✅ Ingestion successfully completed!"
   AND a blue tip:
   "💡 Recommendation: Run the Automated Test Suite to verify data integrity"
        ↓
5. Click the "🧪 Automated Test Suite" tab (same page)
   - Click  🧪 Run Test Suite Now
   - Wait ~10-20 seconds
        ↓
6. Read the results (see below)
```

### Why Tests Are Not Automatic on File Drop

The pipeline **does not auto-run tests** when a file is added to the folder —
and that is intentional:

- The file scanner (`scan_input_dir`) only **detects** files; it does not parse
  or validate them.
- The operator must click **🚀 Ingest New Files** to trigger the pipeline. This
  is a deliberate human checkpoint — the operator can visually inspect the
  detected file list before committing.
- Tests run **after** ingestion, not before, because the Tier 2 (live)
  integration tests need the file to be on disk at the path `cfg` points to.

**Future enhancement (Backlog):** Wire a `post_ingestion_hook` so that
`run_pipeline()` automatically calls `pytest` in a subprocess at the end of
ingestion and stores pass/fail count in the DB. This would close the gap
and make tests truly automatic. Until then, the blue tip banner after
ingestion is the operator's prompt.

---

## What the Operator Sees When Tests Run

### All Tests Pass
```
✅ All 566 test cases passed successfully!
⏭️  3 test cases skipped.
[📋 Show Passed Test List]  ← expandable, shows every test name
```

**Next step:** Nothing. Proceed to the Weekly Reconciliation view.

---

### Some Tests Fail — What the Screen Shows

```
❌ 2 test cases failed (out of 566 total)

Failed Test Details:
🔴 TestParsePayroll ➔ test_paycheck_date  (FAILED)
  AssertionError: assert '2026-06-18' == '2026-07-04'
  where '2026-06-18' = str(self.data['paycheck_date'])

🔴 TestFilterByDosRange ➔ test_filters_to_week  (FAILED)
  AssertionError: assert 0 > 0
```

---

## Operator Decision Tree — What To Do When a Test Fails

Below is the complete decision tree. Each test class maps to one specific
next action.

### Tier 2 Live-File Test Failures

These are the only tests that can fail after dropping a new file. Tier 1
(synthetic) tests are structural and should never fail after a file drop —
if they do, it means the source code was also changed.

| Failing Test Class | What It Means | Operator Next Step |
|--------------------|---------------|-------------------|
| `TestParsePayroll` → `test_paycheck_date` or `test_week_dates` | The new payroll file has a different date format in row 1/2 than expected | Flag to developer. Open the file and check rows 1-2. The date might be in a non-standard cell position. |
| `TestParsePayroll` → `test_records_non_empty` | The payroll file has 0 detail rows parsed | Open the file. Check that the MMDDYYYY sheet exists and has data below row 3. The file may be a template or empty. |
| `TestAggregatePayrollHours` → `test_hours_are_positive` | A negative hours value exists in the payroll file | Open the file and search for negative values in Regular hrs / Respite hrs columns. Could be a data entry error. |
| `TestParseRemittance` → `test_non_empty` | The remittance file parsed 0 records | Check that the sheet is named exactly `"Remittance Report Template"`. A renamed sheet will silently fail. |
| `TestParseRemittance` → `test_tcn_deduplication` | Duplicate TCN+date+type+batch keys found | This indicates two rows in the remittance file are fully identical. Flag to billing team — may be a double-entry. |
| `TestFilterByDosRange` → `test_filters_to_week` | No remittance records fall within the payroll week | The remittance file may not yet include the current week's claims, OR the payroll week dates don't align. Check that the payroll week (rows 1-2) matches the remittance dates of service. This is normal if remittance lags behind payroll by more than 1 week. **Not necessarily an error.** |
| `TestPipeline` → `test_recon_rows_nonzero` | Reconciliation produced 0 rows | Name matching completely failed — no payroll client could be matched to any remittance client. Check the Name Match sheet in the Weekly Recon Excel file. |
| `TestPipeline` → `test_unmatched_clients` | One or more payroll clients have no remittance match | Open Name Match Manager in the app. Add the unmatched client name mapping. Then click **🔁 Rebuild Reconciliation** in Data Management. |
| `TestSeedTracker` → any | EVV Billing Log structure changed | Check the EVV file column headers against what the seeder expects. Flag to developer. |

### Skipped Tests (Not Failures)

Skipped tests are **normal and expected**. They mean the required file
was not found on disk (e.g. EVV file absent). They do not indicate a problem.

```
⏭️  3 test cases skipped.
```

This is fine. The skip guard is:
```python
pytest.importorskip  /  pytest.mark.skipif(not cfg.evv_tracker_file.exists(), ...)
```

### Tier 1 Tests Failing After a File Drop (Unusual)

If a purely structural test like `TestComputeResult` or `TestMakeKey` fails
after a file drop and **no code was changed**, it almost certainly means:

1. A new Python package was installed that broke something, or
2. The `src/` directory has uncommitted changes someone made directly
   on the server

In both cases: **flag to developer immediately**. Do not proceed with ingestion.

---

## Recommended Addition to Operator SOP

Add these two lines to whatever SOP document the operator follows weekly:

> **After every file ingestion:**
> 1. Go to Admin → Data Management → 🧪 Automated Test Suite → click **Run Test Suite Now**
> 2. If any red 🔴 failures appear, compare against the decision tree in `TESTING.md` before proceeding


## Running the Tests

### Full suite
```bash
cd /path/to/remittance_recon
pytest tests/ -v
```

### Tier 1 only (fast, no real files)
```bash
pytest tests/ -v --ignore=tests/test_payroll_parser.py \
  --ignore=tests/test_remittance_parser.py \
  --ignore=tests/test_pipeline.py \
  --ignore=tests/test_queries.py \
  --ignore=tests/test_evv_tracker_validation.py
```

### Single module
```bash
pytest tests/test_reconciliation.py tests/test_reconciliation_extended.py -v
```

### With coverage report
```bash
pytest tests/ --cov=src --cov-report=term-missing
```

---

## Source-to-Test Traceability Matrix

| Source Module | Original Tests | New Tests Added |
|---------------|---------------|----------------|
| `src/etl/reconciliation.py` | `test_reconciliation.py` (84) | `test_reconciliation_extended.py` (42) |
| `src/etl/payroll.py` | `test_payroll_parser.py` (22) | `test_payroll_parser_extended.py` (20) |
| `src/etl/remittance.py` | `test_remittance_parser.py` (42) | `test_remittance_parser_extended.py` (16) |
| `src/etl/name_match.py` | `test_name_match.py` (34) | `test_name_match_extended.py` (26) |
| `src/etl/file_watcher.py` | *(none)* | `test_file_watcher.py` (34) |
| `src/etl/pipeline.py` | `test_pipeline.py` (20) | `test_pipeline_unit.py` (56) + `test_pipeline_extended.py` (18) |
| `src/etl/seed_tracker.py` | *(none)* | `test_seed_tracker.py` (24) |
| `src/db/schema.py` | *(none)* | `test_schema.py` (24) |
| `src/db/connection.py` | *(none)* | `test_schema.py` (included above) |
| `src/db/queries.py` | `test_queries.py` (60) | `test_queries_extended.py` (20) |
| `src/ai/chat.py` | *(none)* | `test_ai_chat.py` (36) |
| EVV Tracker validation | `test_evv_tracker_validation.py` (12) | *(none — adequate)* |

**Total: 566 test functions across 18 files.**
