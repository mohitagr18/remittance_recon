from pathlib import Path
from src.db.connection import get_persistent_conn
import pandas as pd

conn = get_persistent_conn(Path('data/recon.duckdb'))
print(conn.execute("SELECT id, client_name, payer, first_dos, last_dos, override, override_reason, notes FROM unskilled_remit_tracker WHERE client_name ILIKE '%Belfield%'").df())
