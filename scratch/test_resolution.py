import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import duckdb
from src.etl.pipeline import rebuild_reconciliation, load_name_match_from_db, load_copay_clients_from_db
from src.db.connection import get_persistent_conn

db_path = Path("data/recon.duckdb")
conn = get_persistent_conn(db_path)

print("Running rebuild_reconciliation...")
name_mapping = load_name_match_from_db(conn)
copay_set = load_copay_clients_from_db(conn)
summary = rebuild_reconciliation(conn, name_mapping, copay_set)

print(f"Rebuild done: {summary.recon_rows} rows")

import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1200)

print("\n--- Pegram Reconciliation rows ---")
df_pegram = conn.execute("""
    SELECT week_start_date, client_name_payroll, insurance, payroll_hours, billed_hours, paid_hours, result_simple, result_detailed
    FROM reconciliation 
    WHERE client_name_payroll ILIKE '%Soleil%'
    ORDER BY week_start_date
""").fetchdf()
print(df_pegram)

print("\n--- Drewry Reconciliation rows ---")
df_drewry = conn.execute("""
    SELECT week_start_date, client_name_payroll, insurance, payroll_hours, billed_hours, paid_hours, result_simple, result_detailed
    FROM reconciliation 
    WHERE client_name_payroll ILIKE '%Drewry%'
    ORDER BY week_start_date
""").fetchdf()
print(df_drewry)
