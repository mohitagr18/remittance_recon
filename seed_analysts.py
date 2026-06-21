from pathlib import Path
from src.db.connection import get_persistent_conn
import pandas as pd

conn = get_persistent_conn(Path('data/recon.duckdb'))

# Check if analysts table is empty
count = conn.execute("SELECT COUNT(*) FROM analysts").fetchone()[0]

if count == 0:
    print("Seeding analysts...")
    default_analysts = ["MA", "MNL", "YN", "Connie", "Pragya"]
    for name in default_analysts:
        conn.execute("INSERT INTO analysts (id, name) VALUES (nextval('seq_analysts'), ?)", [name])
    conn.commit()
    print("Analysts seeded!")
else:
    print(f"Table already has {count} analysts.")
