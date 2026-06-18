"""
src/db/connection.py
DuckDB connection manager – provides read-write and read-only connections.

WAL-recovery: if DuckDB raises an InternalException while replaying the WAL
(a known crash-recovery bug when ADD COLUMN DEFAULT is left uncommitted),
we delete the corrupt .wal file and retry once.  The schema migration in
create_all() is idempotent (IF NOT EXISTS / re-runs on every startup), so
dropping the WAL is always safe for this codebase.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb

log = logging.getLogger(__name__)


def _wal_path(db_path: Path) -> Path:
    return db_path.with_suffix(db_path.suffix + ".wal")


def _connect_safe(db_path: Path, **kwargs) -> duckdb.DuckDBPyConnection:
    """Connect to DuckDB, auto-deleting a corrupt WAL and retrying once."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return duckdb.connect(str(db_path), **kwargs)
    except duckdb.duckdb.InternalException as exc:
        wal = _wal_path(db_path)
        if "Failure while replaying WAL" in str(exc) and wal.exists():
            log.warning(
                "Corrupt WAL detected at %s – deleting and retrying. "
                "Original error: %s",
                wal,
                exc,
            )
            wal.unlink()
            return duckdb.connect(str(db_path), **kwargs)
        raise


@contextmanager
def get_conn(
    db_path: Path, read_only: bool = False
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Context-managed DuckDB connection."""
    conn = _connect_safe(db_path, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def get_persistent_conn(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Return a long-lived read-write connection (caller must close)."""
    return _connect_safe(db_path)
