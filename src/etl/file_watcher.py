"""
src/etl/file_watcher.py
Lightweight file scanner to track ingestion status of source Excel files.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import duckdb

log = logging.getLogger(__name__)

@dataclass
class PendingFile:
    path: Path
    filename: str
    file_type: str  # 'payroll' | 'remittance'
    file_hash: str
    status: str     # 'Ingested' | 'New' | 'Changed'
    row_count: int | None = None
    week_start: date | None = None
    week_end: date | None = None


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_file_status(conn: duckdb.DuckDBPyConnection, filename: str, file_hash: str) -> str:
    """Query ingested_files to check if the file is Ingested, Changed, or New."""
    # Check exact match first
    res = conn.execute(
        "SELECT file_hash FROM ingested_files WHERE filename = ?",
        [filename]
    ).fetchall()
    
    if not res:
        return "New"
    
    # If we have matches, see if the hash is the same
    for (existing_hash,) in res:
        if existing_hash == file_hash:
            return "Ingested"
            
    return "Changed"


def scan_input_dir(input_dir: Path, conn: duckdb.DuckDBPyConnection) -> list[PendingFile]:
    """
    Scan input_dir/payroll and input_dir/master_remit for files.
    Returns list of PendingFile objects with their DB status.
    """
    files: list[PendingFile] = []
    
    payroll_dir = input_dir / "payroll"
    remit_dir = input_dir / "master_remit"
    
    # Ensure directories exist
    payroll_dir.mkdir(parents=True, exist_ok=True)
    remit_dir.mkdir(parents=True, exist_ok=True)
    
    # Scan payroll
    for p in payroll_dir.glob("*.xlsx"):
        if p.name.startswith("~$"):  # Ignore excel temp files
            continue
        file_hash = compute_file_hash(p)
        status = get_file_status(conn, p.name, file_hash)
        files.append(PendingFile(
            path=p,
            filename=p.name,
            file_type="payroll",
            file_hash=file_hash,
            status=status
        ))
        
    # Scan remittance
    for p in remit_dir.glob("*.xlsx"):
        if p.name.startswith("~$"):
            continue
        file_hash = compute_file_hash(p)
        status = get_file_status(conn, p.name, file_hash)
        files.append(PendingFile(
            path=p,
            filename=p.name,
            file_type="remittance",
            file_hash=file_hash,
            status=status
        ))
        
    return files


def archive_file(file_path: Path, archive_dir: Path) -> Path:
    """Move a file to the archive directory, renaming if a conflict exists."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest_path = archive_dir / file_path.name
    
    # Avoid collisions
    if dest_path.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while (archive_dir / f"{stem}_{counter}{suffix}").exists():
            counter += 1
        dest_path = archive_dir / f"{stem}_{counter}{suffix}"
        
    log.info("Archiving %s to %s", file_path, dest_path)
    shutil.move(str(file_path), str(dest_path))
    return dest_path
