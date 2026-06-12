"""
src/db/connection.py
DuckDB connection manager — provides read-write and read-only connections.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb


@contextmanager
def get_conn(db_path: Path, read_only: bool = False) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Context-managed DuckDB connection."""
    conn = duckdb.connect(str(db_path), read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def get_persistent_conn(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Return a long-lived read-write connection (caller must close)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))
