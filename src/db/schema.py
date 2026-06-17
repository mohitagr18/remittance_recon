"""
src/db/schema.py
DuckDB schema — CREATE TABLE IF NOT EXISTS statements for all tables.
Call create_all(conn) to initialise a fresh database.
"""

from __future__ import annotations

import duckdb

_DDL = """
-- ── Reference Tables ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS name_match (
    id         INTEGER PRIMARY KEY,
    payroll_name    VARCHAR NOT NULL,
    remittance_name VARCHAR,          -- NULL means the name maps to "Not Available"
    is_active  BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS copay_clients (
    id             INTEGER PRIMARY KEY,
    client_name    VARCHAR NOT NULL,   -- payroll name (may include role suffix)
    insurance      VARCHAR,
    is_active      BOOLEAN DEFAULT TRUE,
    copay_amount   DECIMAL(10,2),      -- monthly copay dollar amount
    effective_from DATE,               -- copay start date (NULL = unknown)
    effective_to   DATE,               -- copay end date (NULL = still active)
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id  VARCHAR PRIMARY KEY,
    last_name    VARCHAR,
    first_name   VARCHAR,
    full_name    VARCHAR,            -- "Last, First"
    status       VARCHAR            -- A = Active, T = Terminated
);

-- ── Fact Tables ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS payroll (
    id                     INTEGER PRIMARY KEY,
    week_start_date        DATE NOT NULL,
    week_end_date          DATE NOT NULL,
    paycheck_date          DATE NOT NULL,
    client_name_raw        VARCHAR NOT NULL,
    insurance              VARCHAR,
    employee_name          VARCHAR,
    employee_id            VARCHAR,
    regular_hours          DECIMAL(10,2),
    respite_hours          DECIMAL(10,2),
    total_hours            DECIMAL(10,2),
    source_file            VARCHAR,
    loaded_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (week_start_date, client_name_raw, employee_id, employee_name)
);

CREATE TABLE IF NOT EXISTS remittance (
    id                  INTEGER PRIMARY KEY,
    batch               INTEGER,
    payment_date        DATE,
    transaction         VARCHAR,
    match_status        VARCHAR,
    claim_number        VARCHAR,
    transaction_type    VARCHAR,
    charge_amount       DECIMAL(12,2),
    payment_amount      DECIMAL(12,2),
    allowed_amount      DECIMAL(12,2),
    client_first_name   VARCHAR,
    client_last_name    VARCHAR,
    client_name_combined VARCHAR,   -- "LAST, FIRST" (col 18)
    first_dos           DATE,
    last_dos            DATE,
    tcn                 VARCHAR NOT NULL,
    billed_hours        DECIMAL(10,2),
    paid_hours          DECIMAL(10,2),
    hours_remaining     DECIMAL(10,2),
    insurance           VARCHAR,    -- col 20
    payment_value       DECIMAL(12,2),
    month_label         VARCHAR,
    source_file         VARCHAR,
    loaded_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_latest           BOOLEAN DEFAULT TRUE,
    UNIQUE (tcn, payment_date, transaction_type, batch)
);

-- ── Golden Record ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reconciliation (
    id                      INTEGER PRIMARY KEY,
    week_start_date         DATE NOT NULL,
    week_end_date           DATE NOT NULL,
    paycheck_date           DATE,
    insurance               VARCHAR,
    client_name_payroll     VARCHAR,
    client_name_remittance  VARCHAR,
    payroll_hours           DECIMAL(10,2) DEFAULT 0,
    billed_hours            DECIMAL(10,2) DEFAULT 0,
    paid_hours              DECIMAL(10,2) DEFAULT 0,
    payroll_vs_billed       DECIMAL(10,2),
    billing_vs_paid         DECIMAL(10,2),
    payroll_vs_paid         DECIMAL(10,2),
    result_simple           VARCHAR,    -- Good | Follow up | No Payroll Data | etc.
    result_detailed         VARCHAR,    -- Not Billed | Billed Short | Paid Less | etc.
    is_copay_client         BOOLEAN DEFAULT FALSE,
    match_status            VARCHAR DEFAULT 'MATCHED', -- MATCHED | UNMATCHED | NOT_AVAILABLE
    analyst_override        VARCHAR,    -- YN Good, UD Good if carried from source
    yash_comments           TEXT,
    connie_comments         TEXT,
    care_type               VARCHAR,    -- Skilled | Unskilled
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Ingested Files ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingested_files (
    id            INTEGER PRIMARY KEY,
    filename      VARCHAR NOT NULL,
    file_type     VARCHAR NOT NULL,   -- 'payroll' | 'remittance' | 'recon'
    file_hash     VARCHAR NOT NULL,   -- SHA-256 of file content
    file_path     VARCHAR,
    row_count     INTEGER,
    week_start    DATE,               -- populated for payroll files (week start) and remittance files (min date)
    week_end      DATE,               -- populated for payroll files (week end) and remittance files (max date)
    ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (filename, file_hash)      -- same filename+hash = already ingested
);

-- ── Analyst Workflow ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rebill_tracker (
    id                  INTEGER PRIMARY KEY,
    reconciliation_id   INTEGER REFERENCES reconciliation(id),
    tcn                 VARCHAR,
    denial_code         VARCHAR,
    rebill_date         DATE,
    status              VARCHAR DEFAULT 'PENDING',  -- PENDING|SUBMITTED|PAID|DENIED
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_actions (
    id                INTEGER PRIMARY KEY,
    reconciliation_id INTEGER REFERENCES reconciliation(id),
    action            VARCHAR,       -- MARK_REVIEWED | SEND_TO_REBILL
    performed_by      VARCHAR,
    performed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes             TEXT
);

-- ── Sequences ─────────────────────────────────────────────────────────────────
CREATE SEQUENCE IF NOT EXISTS seq_name_match      START 1;
CREATE SEQUENCE IF NOT EXISTS seq_copay_clients   START 1;
CREATE SEQUENCE IF NOT EXISTS seq_employees       START 1;
CREATE SEQUENCE IF NOT EXISTS seq_payroll         START 1;
CREATE SEQUENCE IF NOT EXISTS seq_remittance      START 1;
CREATE SEQUENCE IF NOT EXISTS seq_reconciliation  START 1;

-- ── Skilled Tracker ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS skilled_tracker_clients (
    id              INTEGER PRIMARY KEY,
    display_name    VARCHAR NOT NULL,
    bill_code       VARCHAR,
    service_type    VARCHAR,
    remittance_name VARCHAR,
    is_active       BOOLEAN DEFAULT TRUE,
    deactivated_from DATE DEFAULT NULL,
    added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (display_name, bill_code)
);

CREATE TABLE IF NOT EXISTS skilled_tracker_comments (
    id              INTEGER PRIMARY KEY,
    display_name    VARCHAR NOT NULL,
    bill_code       VARCHAR NOT NULL,
    billing_week    VARCHAR NOT NULL,
    comment_text    TEXT NOT NULL,
    author          VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tracker_validation_runs (
    id              INTEGER PRIMARY KEY,
    run_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    excel_filename  VARCHAR,
    total_tests     INTEGER,
    passed_tests    INTEGER,
    failed_tests    INTEGER,
    report_json     TEXT
);

CREATE SEQUENCE IF NOT EXISTS seq_skilled_tracker_clients START 1;
CREATE SEQUENCE IF NOT EXISTS seq_skilled_tracker_comments START 1;
CREATE SEQUENCE IF NOT EXISTS seq_tracker_validation_runs START 1;

CREATE SEQUENCE IF NOT EXISTS seq_rebill_tracker  START 1;
CREATE SEQUENCE IF NOT EXISTS seq_review_actions  START 1;
CREATE SEQUENCE IF NOT EXISTS seq_ingested_files  START 1;

"""


def create_all(conn: duckdb.DuckDBPyConnection) -> None:
    """Run all DDL statements against an open connection."""
    for stmt in _DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    # Migrations: add columns that didn't exist in older schema versions
    conn.execute("ALTER TABLE skilled_tracker_clients ADD COLUMN IF NOT EXISTS deactivated_from DATE DEFAULT NULL")
    conn.commit()
