# Payroll-Billing-Remittance Reconciliation Application

## Goal

Build a Phase 1 reconciliation application that unifies three Excel data sources (Payroll, Remittance, Weekly Recon) into a Golden Client Record stored in DuckDB, with a Streamlit UI for the COO, billing analysts, and an AI-powered natural language query layer.

---

## Data Analysis Findings

> [!IMPORTANT]
> The following findings are based on inspecting the actual input files. They deviate from the original spec in several ways that affect implementation.

### Payroll File (`EmpTimeCardReport - PY 03062026.xlsx`)

| Property | Value |
|----------|-------|
| Data sheet | `03062026` (named after paycheck date) |
| Header row | Row 0 |
| Data rows | 331 client-aide pairs |
| Columns | `Employee Name`, `Client`, `Dept`, `Regular`, `Respite`, `Total`, + 6 empty cols |
| Employee master sheet | `Paylocity Mapping` — 246 employees with ID, Name, Department, Position, Status, Hire Date |
| Extra sheet | `Sheet4` — empty (1 row, no data) |

**Parsing notes:**
- The sheet name is the paycheck date in `MMDDYYYY` format — must extract this as `week_ending_date`
- `Dept` column contains codes like `200 - PCA`, `700 - LPN` — can extract role from this
- A single client may appear with multiple aides (one row per aide-client pair)
- For reconciliation, we need to **aggregate** total hours per client across all aides

### Remittance File (`V5.1 2026 Remittance Report Master Updated 05052026.xlsx`)

| Property | Value |
|----------|-------|
| Sheet | `Remittance Report Template` |
| Header row | **Row 3** (Row 0 is metadata: "Last uploaded remittance sheet is dated", Rows 1-2 are blank) |
| Data rows | ~32,148 claim records |
| Date range | May 2025 → May 2026 |
| Unique clients | 196 |
| Unique TCNs | 31,941 (211 duplicates exist) |

**Actual column layout (22 columns, not 20):**

| Index | Column | Example | Notes |
|-------|--------|---------|-------|
| 0 | Batch | `1120.0` | Float |
| 1 | Date | `'5/1/2025'` | **String**, not datetime |
| 2 | Transaction | `'Payment'` | |
| 3 | Match Status | `'Matched'`, `'Handle Manually'` | |
| 4 | Claim | `31926.0` | Float (Claim #) |
| 5 | Transaction Type | `'Paid in Full'`, `'Denial/Reversal'` | |
| 6 | Charge | `'$694.05'` | **String** with `$` and `,` — must parse |
| 7 | Payment | `'$694.05'` | Same format |
| 8 | Allowed | `'$694.05'` | Same format |
| 9 | First Name | `'GEORGE'` | ALL CAPS |
| 10 | Last Name | `'FOSTER'` | ALL CAPS |
| 11 | First DOS | `'3/19/2025'` | **String** date |
| 12 | Last DOS | `'3/25/2025'` | **String** date |
| 13 | TCN | `'25118153425'` | Unique claim key |
| 14 | Billed Hrs | `35` | Numeric |
| 15 | Paid Hrs | `35` | Numeric |
| 16 | Hrs Remaining | `0` | Numeric (can be negative) |
| 17 | Client | `'FOSTER GEORGE'` | Space-separated, ALL CAPS, no comma |
| 18 | Last Name, First Name | `'FOSTER, GEORGE'` | Comma-separated, ALL CAPS — **this is what the spec calls "Client"** |
| 19 | Month | `'3/'` | Partial — for grouping |
| 20 | Insurance | `'Molina'` | **Actual payer name** |
| 21 | Payment Value | `694.05` | Numeric version of Payment col |

> [!WARNING]
> The spec described column 18 as "Insurance" and listed only 20 columns. The actual file has 22 columns. Column 18 is `Last Name, First Name` (the normalized client name). The real **Insurance/Payer** is column 20. Column 21 (`Payment Value`) is the numeric equivalent of column 7 (`Payment` string). I will use column 20 for insurance and column 21 for payment amounts.

**Transaction type distribution:**
- Paid in Full: 26,876
- Paid with Exception: 2,720
- Paid at UC Rate: 2,190
- Denial/Reversal: 365

### Weekly Recon File (`Payroll-Billing-Remittance 02182026-02242026.xlsx`)

**5 sheets:**

1. **`Payroll-Billing-Remmitance`** — The validation target (142 data rows)
   - Columns: Insurance, Client, SUM of Total Hrs, Client Vlookup, Billed Hours, Paid Hours, Payroll vs Billed, Billing vs Paid, Payroll vs Paid, Result, Yash Comments, Ms. Connie Comments
   - Contains **subtotal rows** (e.g., `Aetna Total`, `Grand Total`, `Work Week:`) — must be filtered out
   - Result values: `Good` (74), `Follow up` (51), `YN Good` (25), `No Payroll Hours` (6), `UD Good` (2)
   - Insurance payers: Anthem (38), Sentara (38), UHC (33), PDN (16), Medicaid (14), Aetna (12), Humana (7)

2. **`Remmitance Data`** — Pivot of remittance by insurance/client (199 rows, grouped with sub-headers)

3. **`Name Match`** — 166 mappings, including:
   - Simple suffix stripping: `Carroll, Robert PCA` → `Carroll, Robert`
   - Role variant merging: `Faulkner, Shanada PCA` / `Faulkner, Shanada RN` / `Faulkner, Shanada (LPN)` → `Faulkner, Shanada`
   - Spacing normalization: `Baker,  Joselyn` (double space) → `Baker, Joselyn`
   - ~30 entries mapping to `Not Available` (private/non-billable clients)
   - Name corrections: `RICHEY, MICHAH` → `RICHEY, MICAH`, `LEMUS-MAEDA, YOSUANI` → `LEMUS MAEDA, YOSUANI`

4. **`Copay`** — 44 clients with copay obligations, grouped by Insurance (Aetna, Amerihealth, DC Medicaid, Priority Partners). These clients use **payroll names** (e.g., `Harris, Patricia PCA`).

5. **`Sheet1`** — Raw payroll data (identical to the payroll file's main sheet)

---

## User Review Required

> [!IMPORTANT]
> **Result values in the existing recon file don't exactly match the spec.** The spec defines detailed categories like `Follow Up: Not Billed`, `Follow Up: Billed Short`, etc. But the existing recon file uses simpler labels: `Good`, `Follow up`, `YN Good`, `UD Good`, `No Payroll Hours`. I propose implementing BOTH:
> 1. A `result_simple` column matching the existing Excel values (for validation)
> 2. A `result_detailed` column with the richer categories from the spec (for the UI)
>
> **Does this approach work, or should I match the existing labels exactly?**

> [!WARNING]
> **Two unknown result codes**: `YN Good` (25 occurrences) and `UD Good` (2 occurrences) are not defined in the spec. Based on context, I believe:
> - `YN Good` = a status set by Yash (analyst comment-based override, possibly "Yash Noted — Good")
> - `UD Good` = "Under Discussion — Good" or a similar analyst override
>
> **Please confirm what these mean.** I'll treat them as analyst-overridden statuses that map to `Good` in the system, preservable as override flags.

> [!IMPORTANT]
> **Copay list uses payroll names** (e.g., `Harris, Patricia PCA`), not remittance names. When checking if a client is on the copay list, I should match against the original payroll name OR the normalized remittance name. **Confirm this is correct.**

> [!IMPORTANT]
> **Insurance mapping discrepancy.** The recon file uses payer names like `Anthem`, `Sentara`, `UHC`, `PDN`, `Medicaid`, `Aetna`, `Humana`. The remittance file uses names like `Molina`, `United`, `Aetna`, `PDN`. There's no direct mapping table in the files. Questions:
> - Is `United` = `UHC`?  
> - Where does `Anthem`, `Sentara`, `Humana`, `Medicaid` come from — the payroll file's `Dept` column, or somewhere else?
> - Do I need an Insurance name normalization table similar to the Name Match table?

---

## Open Questions

1. **How is insurance determined per client in the payroll file?** The payroll file has no Insurance column — only `Dept` (e.g., `200 - PCA`). In the recon file, each client has an insurance. Where does this mapping come from?

2. **What date range should the remittance data be filtered to for the 02/18–02/24 week?** The remittance file contains claims dating back to Oct 2025. The recon file shows billed/paid hours for the specific week — how are remittance records matched to a specific payroll week? By `First DOS` / `Last DOS` falling within the payroll week?

3. **The `Remittance Design.docx` file** — should I read this for additional design requirements, or does it contain the same information you've already provided in the prompt?

4. **Multi-week operation**: The payroll file covers paycheck date 03/06/2026 but the recon file covers week 02/18–02/24/2026. Are these always offset by ~2 weeks (payroll lag)? How should I handle the date mapping?

5. **Name case sensitivity**: Payroll names are mixed case (`Baker, Joselyn`), remittance names are ALL CAPS (`BAKER, JOSELYN`). The Name Match table appears in mixed case. Should matching be case-insensitive?

---

## Proposed Changes

### Phase 0: Project Setup

#### [NEW] [pyproject.toml](file:///Users/mohit/Documents/GitHub/remittance_recon/pyproject.toml)
- Project metadata and all dependencies declared for `uv sync`
- Dependencies: `duckdb`, `pandas`, `openpyxl`, `streamlit`, `plotly`, `openai`, `google-generativeai`, `python-dotenv`, `pytest`

#### [NEW] [.env.example](file:///Users/mohit/Documents/GitHub/remittance_recon/.env.example)
- Template with all environment variables: file paths, LLM config, DB path

#### [NEW] [PROGRESS.md](file:///Users/mohit/Documents/GitHub/remittance_recon/PROGRESS.md)
- Agent continuity checklist per spec

#### Project structure:
```
remittance_recon/
├── input/                          # Source Excel files (existing)
├── src/
│   ├── __init__.py
│   ├── config.py                   # Env var loading, path resolution
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py           # DuckDB connection manager
│   │   ├── schema.py               # Table definitions + migrations
│   │   └── queries.py              # All validated SQL queries
│   ├── etl/
│   │   ├── __init__.py
│   │   ├── payroll.py              # Payroll Excel parser
│   │   ├── remittance.py           # Remittance Excel parser
│   │   ├── recon.py                # Weekly recon file parser
│   │   ├── name_match.py           # Name normalization engine
│   │   ├── reconciliation.py       # Flag computation logic
│   │   └── pipeline.py             # Orchestrator: read → normalize → reconcile → write
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── chat.py                 # NL → SQL → answer engine
│   │   └── prompts.py              # System prompts and few-shot examples
│   └── ui/
│       ├── __init__.py
│       ├── app.py                  # Streamlit entry point
│       ├── pages/
│       │   ├── 1_dashboard.py      # COO Executive Dashboard
│       │   ├── 2_client_ledger.py  # Client Ledger
│       │   ├── 3_workbench.py      # Billing Analyst Workbench
│       │   └── 4_settings.py       # Settings / Name Match Manager
│       ├── components/
│       │   ├── kpi_cards.py        # Reusable KPI card component
│       │   ├── charts.py           # Plotly chart builders
│       │   └── filters.py          # Shared filter widgets
│       └── styles/
│           └── theme.py            # Streamlit theme config
├── tests/
│   ├── __init__.py
│   ├── test_payroll_parser.py
│   ├── test_remittance_parser.py
│   ├── test_name_match.py
│   ├── test_reconciliation.py
│   ├── test_queries.py
│   └── test_etl_validation.py      # Row-by-row comparison vs Excel
├── data/
│   └── recon.duckdb                # Generated database (gitignored)
├── pyproject.toml
├── .env.example
├── .env                            # User-created (gitignored)
├── PROGRESS.md
└── README.md
```

---

### Phase 1: ETL Pipeline (Step 1)

#### [NEW] src/config.py
- Load `.env` via `python-dotenv`
- Resolve all file paths from env vars with sensible defaults
- Config dataclass with: `PAYROLL_FILE`, `REMITTANCE_FILE`, `RECON_FILE`, `DB_PATH`, `LLM_PROVIDER`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`

#### [NEW] src/db/schema.py
DuckDB schema design:

```sql
-- Core reference tables
CREATE TABLE IF NOT EXISTS name_match (
    id INTEGER PRIMARY KEY,
    payroll_name VARCHAR NOT NULL,
    remittance_name VARCHAR,  -- NULL means "Not Available"
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS copay_clients (
    id INTEGER PRIMARY KEY,
    client_name VARCHAR NOT NULL,    -- payroll name
    insurance VARCHAR,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    department VARCHAR,
    position VARCHAR,
    status VARCHAR,  -- Active/Terminated
    hire_date DATE
);

-- Fact tables
CREATE TABLE IF NOT EXISTS payroll (
    id INTEGER PRIMARY KEY,
    week_ending_date DATE NOT NULL,
    employee_name VARCHAR NOT NULL,
    client_name_raw VARCHAR NOT NULL,       -- Original payroll name
    client_name_normalized VARCHAR,          -- After Name Match lookup
    department VARCHAR,
    regular_hours DECIMAL(10,2),
    respite_hours DECIMAL(10,2),
    total_hours DECIMAL(10,2),
    source_file VARCHAR,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remittance (
    id INTEGER PRIMARY KEY,
    batch INTEGER,
    payment_date DATE,
    transaction VARCHAR,
    match_status VARCHAR,
    claim_number VARCHAR,
    transaction_type VARCHAR,    -- Paid in Full, Denial/Reversal, etc.
    charge_amount DECIMAL(12,2),
    payment_amount DECIMAL(12,2),
    allowed_amount DECIMAL(12,2),
    client_first_name VARCHAR,
    client_last_name VARCHAR,
    client_name_combined VARCHAR,    -- "LAST, FIRST" from col 18
    first_dos DATE,
    last_dos DATE,
    tcn VARCHAR NOT NULL,            -- Unique claim key
    billed_hours DECIMAL(10,2),
    paid_hours DECIMAL(10,2),
    hours_remaining DECIMAL(10,2),
    insurance VARCHAR,               -- From col 20
    payment_value DECIMAL(12,2),     -- Numeric from col 21
    month_label VARCHAR,
    source_file VARCHAR,
    file_date DATE,                  -- Date of the remittance file
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_latest BOOLEAN DEFAULT TRUE   -- For TCN dedup: most recent = TRUE
);

-- Golden Record: the reconciliation output
CREATE TABLE IF NOT EXISTS reconciliation (
    id INTEGER PRIMARY KEY,
    week_ending_date DATE NOT NULL,
    insurance VARCHAR,
    client_name_payroll VARCHAR,
    client_name_remittance VARCHAR,
    payroll_hours DECIMAL(10,2) DEFAULT 0,
    billed_hours DECIMAL(10,2) DEFAULT 0,
    paid_hours DECIMAL(10,2) DEFAULT 0,
    payroll_vs_billed DECIMAL(10,2),     -- payroll_hours - billed_hours
    billing_vs_paid DECIMAL(10,2),       -- billed_hours - paid_hours
    payroll_vs_paid DECIMAL(10,2),       -- payroll_hours - paid_hours
    result_simple VARCHAR,               -- Good, Follow up, No Payroll Hours
    result_detailed VARCHAR,             -- Follow Up: Not Billed, etc.
    is_copay_client BOOLEAN DEFAULT FALSE,
    is_name_matched BOOLEAN DEFAULT TRUE,
    match_status VARCHAR DEFAULT 'MATCHED',  -- MATCHED, UNMATCHED, NOT_AVAILABLE
    analyst_override VARCHAR,            -- For YN Good, UD Good type overrides
    yash_comments TEXT,
    connie_comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Rebilling tracker (for Analyst Workbench actions)
CREATE TABLE IF NOT EXISTS rebill_tracker (
    id INTEGER PRIMARY KEY,
    reconciliation_id INTEGER REFERENCES reconciliation(id),
    tcn VARCHAR,
    denial_code VARCHAR,
    rebill_date DATE,
    status VARCHAR DEFAULT 'PENDING',   -- PENDING, SUBMITTED, PAID, DENIED
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Analyst review tracking
CREATE TABLE IF NOT EXISTS review_actions (
    id INTEGER PRIMARY KEY,
    reconciliation_id INTEGER REFERENCES reconciliation(id),
    action VARCHAR,          -- MARK_REVIEWED, SEND_TO_REBILL
    performed_by VARCHAR,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);
```

#### [NEW] src/etl/payroll.py
- Read the payroll Excel file
- Detect the data sheet by name pattern (MMDDYYYY)
- Parse header at row 0
- Extract `Employee Name`, `Client` (raw payroll name), `Dept`, `Regular`, `Respite`, `Total`
- Round all hours to 2 decimal places
- Aggregate total hours per client (summing across all aides)
- Also read `Paylocity Mapping` sheet for employee master data

#### [NEW] src/etl/remittance.py
- Read remittance Excel file
- **Skip rows 0-2** (metadata + blanks), header at **row 3**
- Parse all 22 columns with correct mapping (see data analysis above)
- Parse dollar-string columns (`Charge`, `Payment`, `Allowed`) → float
- Parse date strings → date objects
- Round all hours to 2 decimal places
- Handle TCN deduplication: when same TCN appears multiple times, keep the most recent (by `payment_date`), mark older records as `is_latest = FALSE`

#### [NEW] src/etl/name_match.py
- Load Name Match table from the recon file's `Name Match` sheet
- Build a lookup dictionary: `payroll_name → remittance_name`
- Apply case-insensitive matching
- For names not in the lookup: log as `UNMATCHED`, do NOT drop
- For names mapping to `Not Available`: mark as `NOT_AVAILABLE`
- Also load Copay list and build a set for quick lookup

#### [NEW] src/etl/reconciliation.py
Core reconciliation engine — given payroll hours and remittance hours for a client/week:

```python
def compute_result(payroll_hrs, billed_hrs, paid_hrs, is_copay, tolerance=0.1):
    pvb = round(payroll_hrs - billed_hrs, 2)  # Payroll vs Billed
    bvp = round(billed_hrs - paid_hrs, 2)     # Billing vs Paid
    pvp = round(payroll_hrs - paid_hrs, 2)    # Payroll vs Paid
    
    # No payroll hours
    if payroll_hrs == 0 and billed_hrs == 0:
        return "No Payroll Hours", "No Payroll Hours"
    
    # Copay override
    if is_copay and abs(pvb) > tolerance:
        return "Good", "Good (Copay Expected)"
    
    # All within tolerance
    if abs(pvb) <= tolerance and abs(bvp) <= tolerance:
        return "Good", "Good"
    
    # Payroll vs Billed checks
    if pvb > tolerance:
        if billed_hrs == 0:
            return "Follow up", "Follow Up: Not Billed"
        else:
            return "Follow up", "Follow Up: Billed Short"
    elif pvb < -tolerance:
        return "Follow up", "Follow Up: Billed Extra"
    
    # Billing vs Paid checks (only when pvb is within tolerance)
    if bvp > tolerance:
        if paid_hrs == 0:
            return "Follow up", "Follow Up: Not Paid"
        else:
            return "Follow up", "Follow Up: Paid Less"
    elif bvp < -tolerance:
        return "Follow up", "Follow Up: Overpaid"
    
    return "Good", "Good"
```

#### [NEW] src/etl/pipeline.py
Orchestrator that:
1. Reads payroll → aggregates hours per client
2. Reads remittance → filters by DOS range for the target week → aggregates billed/paid per client
3. Loads Name Match → normalizes client names
4. Loads Copay list
5. Joins payroll + remittance on normalized client name
6. Computes reconciliation flags
7. Writes all tables to DuckDB
8. Returns summary statistics for verification

---

### Phase 2: Query Layer (Step 2)

#### [NEW] src/db/queries.py

Validated SQL queries covering:

1. **Weekly Summary** — Total billed hours, total paid hours, total pending, follow-up count, collection rate %
2. **Follow-Up Items by Reason** — Grouped by `result_detailed`, with client name, insurance, hours, variance
3. **Per-Client Ledger** — All transactions for a given client across all weeks (every positive and negative transaction from remittance)
4. **Payer Collection Rates** — By insurance: sum(paid)/sum(billed), color-coded vs 95% target
5. **Rebilling Tracker** — All items in `rebill_tracker` with status and dates
6. **Top Open Balances** — Clients with highest unpaid amounts
7. **12-Week Rolling Trend** — Weekly billed/paid/pending for the last 12 weeks
8. **Follow-Up Reason Breakdown** — For donut chart
9. **Client Summary** — Insurance, aide(s), authorized hours, YTD billed/collected/pending, collection rate, open claims

---

### Phase 3: Streamlit UI (Step 3)

#### Screen 3a: COO Executive Dashboard
- 5 KPI cards at top: Total Billed ($), Total Collected ($), Pending ($), Follow-Up Count, Collection Rate (%)
- 12-week rolling grouped bar chart (Billed vs Paid vs Pending) — Plotly
- Follow-Up reason breakdown donut chart — Plotly
- Payer collection rate horizontal bar chart (Green ≥ 95%, Yellow 85-95%, Red < 85%)
- Top open balances table
- Filters: Week picker, Insurance multi-select
- **Read-only** — no editing

#### Screen 3b: Client Ledger
- Client search/select dropdown
- Client summary card (insurance, aide(s), authorized hours, YTD stats)
- All-time weekly billed vs paid bar chart
- Full payment ledger table: Date, TCN, DOS range, Transaction Type, Charge, Paid, Status
- Color-coded rows by status (Paid = green, Denied = red, Pending = yellow)

#### Screen 3c: Billing Analyst Workbench
- Follow-Up queue table with filters:
  - Week picker
  - Insurance filter
  - Reason filter (dropdown of `result_detailed` values)
  - "Follow Up Only" toggle
- Action buttons per row: `[Mark Reviewed]`, `[Send to Rebill]`
- Rebilling Tracker panel below — shows rebill items with denial code, date, status
- Client detail sidebar on row click
- AI Chat text box at bottom

#### Screen 3d: Settings / Name Match Manager
- Name Match table with search, inline editing, add new mapping
- `Not Available` entries highlighted
- `UNMATCHED` entries surfaced at the top with "Add Mapping" action
- Copay list management (add/remove clients)
- All changes persist to DuckDB immediately
- Changes take effect on next ETL run

---

### Phase 4: AI Chat Layer (Step 4)

#### [NEW] src/ai/chat.py
- Takes natural language question
- Constructs a prompt with DuckDB schema context + few-shot examples
- Calls LLM (OpenAI GPT-4o or Google Gemini based on `LLM_PROVIDER` env var)
- Extracts SQL from response
- Executes against DuckDB (read-only connection)
- Formats result as plain English with dollar formatting
- Never exposes raw SQL to end users

#### [NEW] src/ai/prompts.py
- System prompt describing all tables, columns, and relationships
- 5+ few-shot examples covering:
  1. "How much did we bill last week?" → weekly summary query
  2. "Which clients have follow-ups?" → follow-up items query
  3. "Show me Baker, Joselyn's payment history" → client ledger query
  4. "What's our collection rate for Anthem?" → payer collection query
  5. "How many claims are pending rebill?" → rebill tracker query

---

## Verification Plan

### Step 1 Validation: ETL Row-by-Row Comparison

**Test**: Run the ETL pipeline on the provided sample files (payroll 03/06/2026, remittance master, recon 02/18–02/24/2026). Compare the output `reconciliation` table against the existing `Payroll-Billing-Remmitance` sheet:

| Column | Tolerance | Method |
|--------|-----------|--------|
| `insurance` | Exact match | String comparison |
| `client_name_payroll` | Exact match | String comparison |
| `payroll_hours` | ±0.1 hrs | `abs(expected - actual) <= 0.1` |
| `billed_hours` | ±0.1 hrs | Same |
| `paid_hours` | ±0.1 hrs | Same |
| `payroll_vs_billed` | ±0.1 hrs | Same |
| `billing_vs_paid` | ±0.1 hrs | Same |
| `payroll_vs_paid` | ±0.1 hrs | Same |
| `result_simple` | Exact match | After mapping `YN Good` → `Good`, `UD Good` → `Good` |

**Acceptance criteria**: ≥95% of rows match. Any mismatches are investigated and explained.

### Step 2 Validation: Query Layer

For each query, show sample output from the test data and verify:
- Correct aggregation (totals match manual calculation)
- Correct filtering (no phantom rows)
- Correct sorting

### Step 3 Validation: UI

After each screen is built, run `streamlit run src/ui/app.py` and have the user visually verify:
- Data displays correctly
- Filters work
- Charts render
- Actions (Mark Reviewed, Send to Rebill) persist

### Step 4 Validation: AI Chat

Test with 5 sample questions:
1. "How much did we bill this week?"
2. "Which clients have follow-ups for Anthem?"
3. "Show me the payment history for Baker, Joselyn"
4. "What's our collection rate by insurance?"
5. "How many claims are in the rebill queue?"

**Acceptance**: Each question returns a correct, plain English answer with proper dollar/number formatting.

### Automated Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test suites
uv run pytest tests/test_payroll_parser.py -v
uv run pytest tests/test_remittance_parser.py -v
uv run pytest tests/test_name_match.py -v
uv run pytest tests/test_reconciliation.py -v
uv run pytest tests/test_etl_validation.py -v   # Row-by-row comparison
uv run pytest tests/test_queries.py -v
```


Phase 2

# Data Persistence, File Watching & Multi-Week Recon

## What This Fixes

Three interconnected problems:

1. **Data gets wiped on every pipeline run** — `DELETE FROM remittance / payroll` before each insert means re-running destroys history. Source files can't be removed safely.
2. **No multi-week visibility** — The reconciliation table only holds the one week matching the loaded payroll file. All other weeks in the remittance master are invisible.
3. **No auto-ingestion** — Adding a new payroll file requires a manual code/CLI change. The system should detect and process new files automatically.

---

## Proposed Changes

### Component 1: DB Schema — `ingested_files` table

#### [MODIFY] [schema.py](file:///Users/mohit/Documents/GitHub/remittance_recon/src/db/schema.py)

Add a new `ingested_files` table to track every source file ever processed:

```sql
CREATE TABLE IF NOT EXISTS ingested_files (
    id            INTEGER PRIMARY KEY,
    filename      VARCHAR NOT NULL,
    file_type     VARCHAR NOT NULL,   -- 'payroll' | 'remittance' | 'recon'
    file_hash     VARCHAR NOT NULL,   -- SHA-256 of file content
    file_path     VARCHAR,
    row_count     INTEGER,
    week_start    DATE,               -- populated for payroll files
    week_end      DATE,
    ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (filename, file_hash)      -- same filename+hash = already ingested
);
```

Also add a **UNIQUE constraint** to the `remittance` table on `tcn` so we can use `INSERT OR IGNORE`:
```sql
ALTER TABLE remittance ADD UNIQUE (tcn);
```

And a **UNIQUE constraint** on `payroll` for deduplication:
```sql
(week_start_date, client_name_raw, employee_id, employee_name)
```

---

### Component 2: ETL — Incremental ingestion

#### [MODIFY] [pipeline.py](file:///Users/mohit/Documents/GitHub/remittance_recon/src/etl/pipeline.py)

Replace destructive `DELETE FROM` + `INSERT` with:

**For remittance:**
- Skip entire file if `(filename, file_hash)` already exists in `ingested_files`
- Otherwise, insert all records with `INSERT OR IGNORE ON CONFLICT (tcn) DO NOTHING`
- Mark file in `ingested_files`

**For payroll:**
- Same skip-if-seen logic on `(filename, file_hash)`
- Insert with conflict ignore on `(week_start_date, client_name_raw, employee_id)`

**Reconciliation rebuild:**
- After ingesting any new payroll file, rebuild `reconciliation` for that week only (not all weeks)
- After ingesting a new remittance file, rebuild reconciliation for all weeks that now have new data

#### [NEW] `src/etl/file_watcher.py`

A lightweight file scanner (no external dependencies):
```python
def scan_input_dir(input_dir: Path) -> list[PendingFile]
```

- Walks `input/` directory
- Classifies files by name pattern:
  - `EmpTimeCardReport*.xlsx` → `payroll`
  - `V*.xlsx` or `*Remittance*.xlsx` → `remittance`
  - `Payroll-Billing-Remittance*.xlsx` → `recon` (name mapping / copay source)
- Computes SHA-256 hash of each file
- Checks against `ingested_files` table
- Returns list of files not yet ingested (new or changed)

---

### Component 3: Multi-week reconciliation

#### [MODIFY] [pipeline.py](file:///Users/mohit/Documents/GitHub/remittance_recon/src/etl/pipeline.py)

Add `build_remittance_only_weeks()` function:

- After ingesting remittance, find all distinct `(week_start, client)` combos in raw `remittance` table that do NOT have a payroll row
- Build reconciliation rows with `payroll_hours = NULL`, `result_simple = 'Remittance Only'`
- This makes ALL weeks visible in the Weekly Recon page

#### [MODIFY] [queries.py](file:///Users/mohit/Documents/GitHub/remittance_recon/src/db/queries.py)

Update `available_weeks()` to pull from **remittance** table (all DOS weeks), not just reconciliation:

```sql
SELECT DISTINCT
    DATE_TRUNC('week', first_dos) AS week_start
FROM remittance
ORDER BY week_start DESC
```

Update `weekly_recon_detail()` to read from a view that joins reconciliation + remittance-only weeks.

---

### Component 4: Streamlit — Data Management page

#### [NEW] `src/ui/pages/5_Data_Management.py`

A dedicated page for ingestion control:

- **File Scanner panel**: Lists all files in `input/` with status (✅ Ingested / 🆕 New / 🔄 Changed)
- **"Ingest New Files" button**: Runs the incremental pipeline for pending files only
- **Ingestion log**: Shows `ingested_files` table — filename, type, rows, date, hash
- **Auto-scan on page load**: Runs `scan_input_dir()` every time the page opens

> [!NOTE]
> No background daemon needed — scanning happens when the page loads or the button is clicked. This is reliable and doesn't require watchdog or cron.

---

### Component 5: Config cleanup

#### [MODIFY] [config.py](file:///Users/mohit/Documents/GitHub/remittance_recon/src/config.py)

- Replace single `payroll_file` / `remittance_file` with `input_dir: Path`
- The scanner finds all relevant files in that directory automatically
- Keep `recon_file` for the name-mapping/copay source (it doesn't change often)

---

## Data Flow After Changes

```
input/ directory
├── EmpTimeCardReport - PY 03062026.xlsx   ← payroll week 1
├── EmpTimeCardReport - PY 03132026.xlsx   ← payroll week 2 (future)
├── V5.1 2026 Remittance Report Master.xlsx ← all remittance weeks
└── Payroll-Billing-Remittance *.xlsx      ← name mapping / copay

         ↓  scan_input_dir() on page load
         
ingested_files table
├── remittance: V5.1 2026... → SHA256: abc → ✅ ingested
└── payroll: EmpTimeCardReport PY 03062026 → ✅ ingested

         ↓  if new file detected

incremental_pipeline(file)
├── remittance: INSERT OR IGNORE on TCN
├── payroll: INSERT OR IGNORE on (week, client, employee)
├── rebuild reconciliation for affected weeks
└── build remittance-only rows for weeks without payroll
```

---

## Verification Plan

### Automated
```bash
pytest tests/ -v
```

### Manual
1. Run full ingest of current files → verify `ingested_files` table populated
2. Re-run ingest → verify no duplicate rows inserted, file skipped
3. Add a new (fake) payroll file → verify new week appears in Weekly Recon
4. Weekly Recon page: select a week from remittance that has no payroll → verify billed/paid shown, payroll column shows `—`
5. Source files can be moved out of `input/` → DB still serves all data

---

## Open Questions

> [!IMPORTANT]
> **Q1: Should the source files be moved/archived after ingestion, or just left in place?**
> The system will be able to function without them once ingested — but leaving them is safer for re-import. Recommendation: leave them, but show "✅ Already in DB" status.

> [!IMPORTANT]
> **Q2: For weeks where only remittance data exists (no payroll), what result label should the reconciliation row show?**
> Options: `"Remittance Only"` (descriptive), `"No Payroll Data"` (same as existing `"No Payroll Hours"`), or just show NULL. Recommend: `"Remittance Only"` as a distinct status.

> [!IMPORTANT]
> **Q3: When a new remittance master file is uploaded (e.g., V5.2), should it fully replace V5.1 records, or append?**
> Since TCN is the dedup key, unchanged claims will be skipped automatically. New/updated claims (new TCN or newer payment_date for same TCN) will be added. This handles incremental remittance updates correctly.

---

# Phase 3: Dashboard Refinements & Bug Fixes

## What This Fixes

1. **Inaccurate "Total Clients" KPI Card**: Currently shows total client-weeks (~8,000) instead of unique active clients (~250).
2. **Missing YTD Date Range Filters**: The COO Executive Dashboard lacks a date range filter, only offering single-week selection. It should default to YTD.
3. **Invalid "Billed Extra" Follow-Up**: Reconciliations flag billing that exceeds payroll as a follow-up ("Billed Extra"), even if the insurance paid 100% of the billed hours.

## Proposed Changes

### Component 1: Queries — `src/db/queries.py`
- **Modify** `weekly_summary()` to return unique clients using `COUNT(DISTINCT COALESCE(client_name_payroll, client_name_remittance))` instead of `COUNT(*)`.
- **Modify** `weekly_summary()`, `rolling_trend()`, `followup_reason_breakdown()`, `top_followup_clients()`, and `payer_collection_rates()` to accept `start_date` and `end_date` parameters and apply them to `week_start_date` bounds.

### Component 2: Reconciliation Logic — `src/etl/reconciliation.py`
- **Modify** `compute_result()` to remove the `"Billed Extra"` follow-up check. If billing exceeds payroll and payment matches billing, mark as `"Good"`, `None`.

### Component 3: COO Dashboard UI — `src/ui/app.py`
- **Modify** `src/ui/app.py` to replace the single-week filter in the sidebar with a **Date Period** selector:
  - Options: `Year to Date (YTD)` (Default), `All Time`, `Custom Range`.
  - Auto-detects the maximum year in the database to define the YTD range starting from January 1st of that year.
  - Dynamically updates all page queries with the resulting date range.

## Verification Plan

### Automated Tests
- Run full suite of unit and integration tests:
  ```bash
  uv run pytest tests/ -v
  ```

### Manual Verification
- Verify that the `Total Clients` KPI card displays the correct number of unique active clients (~205) on the default YTD view.
- Confirm the date preset selector sidebar options function correctly and filter all metrics across the start/end range.
- Confirm that the number of follow-ups drops (from 32 down to 23) because "Billed Extra" claims that are fully paid are resolved to Good.

