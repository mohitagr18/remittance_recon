"""
tests/test_file_watcher.py
Full unit-test coverage for src/etl/file_watcher.py.

Covers:
  - compute_file_hash  (consistency, distinctness, format, manual verification)
  - get_file_status    (New / Ingested / Changed)
  - scan_input_dir     (finds xlsx, skips temp, creates missing dirs, status tagging)
  - archive_file       (moves file, conflict rename, creates archive dir, return value)
"""
from __future__ import annotations
import hashlib
from pathlib import Path

import duckdb
import pytest

from src.db.schema import create_all
from src.etl.file_watcher import (
    archive_file,
    compute_file_hash,
    get_file_status,
    scan_input_dir,
)


def _make_xlsx(path: Path, content: bytes = b"dummy-xlsx") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _db() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    create_all(conn)
    return conn


class TestComputeFileHash:
    def test_consistent_same_file(self, tmp_path):
        """Same file content -> identical hash on two calls."""
        f = _make_xlsx(tmp_path / "p.xlsx", b"abc")
        assert compute_file_hash(f) == compute_file_hash(f)

    def test_different_content_different_hash(self, tmp_path):
        """Different file content -> different hashes."""
        f1 = _make_xlsx(tmp_path / "a.xlsx", b"aaa")
        f2 = _make_xlsx(tmp_path / "b.xlsx", b"bbb")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_sha256_64_char_hex(self, tmp_path):
        """Output is a 64-char lowercase hex string."""
        f = _make_xlsx(tmp_path / "c.xlsx", b"x")
        h = compute_file_hash(f)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_matches_manual_sha256(self, tmp_path):
        """Value matches hashlib.sha256 directly."""
        data = b"test payload"
        f = _make_xlsx(tmp_path / "d.xlsx", data)
        assert compute_file_hash(f) == hashlib.sha256(data).hexdigest()


class TestGetFileStatus:
    def test_new_file_not_in_db(self, tmp_path):
        """File not in ingested_files -> 'New'."""
        conn = _db()
        f = _make_xlsx(tmp_path / "p.xlsx")
        assert get_file_status(conn, f.name, compute_file_hash(f)) == "New"

    def test_ingested_same_hash(self, tmp_path):
        """File registered with same hash -> 'Ingested'."""
        conn = _db()
        f = _make_xlsx(tmp_path / "p.xlsx")
        h = compute_file_hash(f)
        conn.execute(
            "INSERT INTO ingested_files (id, filename, file_type, file_hash, row_count) "
            "VALUES (nextval('seq_ingested_files'), ?, 'payroll', ?, 10)",
            [f.name, h]
        )
        assert get_file_status(conn, f.name, h) == "Ingested"

    def test_changed_different_hash(self, tmp_path):
        """File in DB but hash changed -> 'Changed'."""
        conn = _db()
        f = _make_xlsx(tmp_path / "p.xlsx", b"v1")
        old_hash = "a" * 64
        conn.execute(
            "INSERT INTO ingested_files (id, filename, file_type, file_hash, row_count) "
            "VALUES (nextval('seq_ingested_files'), ?, 'payroll', ?, 10)",
            [f.name, old_hash]
        )
        new_hash = compute_file_hash(f)
        assert new_hash != old_hash
        assert get_file_status(conn, f.name, new_hash) == "Changed"


class TestScanInputDir:
    def test_finds_payroll_and_remittance_xlsx(self, tmp_path):
        """Regular xlsx in payroll/ and master_remit/ are both discovered."""
        _make_xlsx(tmp_path / "payroll" / "report.xlsx")
        _make_xlsx(tmp_path / "master_remit" / "remit.xlsx")
        files = scan_input_dir(tmp_path, _db())
        types = {f.file_type for f in files}
        assert "payroll" in types and "remittance" in types
        assert len(files) == 2

    def test_skips_temp_excel_files(self, tmp_path):
        """~$-prefixed files (Excel lock files) are excluded."""
        _make_xlsx(tmp_path / "payroll" / "~$locked.xlsx")
        _make_xlsx(tmp_path / "payroll" / "real.xlsx")
        files = scan_input_dir(tmp_path, _db())
        assert len(files) == 1
        assert files[0].filename == "real.xlsx"

    def test_creates_missing_directories(self, tmp_path):
        """scan_input_dir creates payroll/ and master_remit/ if absent."""
        payroll_dir = tmp_path / "payroll"
        remit_dir   = tmp_path / "master_remit"
        scan_input_dir(tmp_path, _db())
        assert payroll_dir.exists() and remit_dir.exists()

    def test_empty_dirs_return_empty_list(self, tmp_path):
        """No xlsx files -> empty list, no crash."""
        assert scan_input_dir(tmp_path, _db()) == []

    def test_pending_file_attributes(self, tmp_path):
        """PendingFile has correct file_type, filename, and 64-char hash."""
        _make_xlsx(tmp_path / "payroll" / "week.xlsx", b"data")
        pf = scan_input_dir(tmp_path, _db())[0]
        assert pf.file_type == "payroll"
        assert pf.filename == "week.xlsx"
        assert len(pf.file_hash) == 64

    def test_already_ingested_file_gets_ingested_status(self, tmp_path):
        """A file already in DB with same hash -> status='Ingested'."""
        f = _make_xlsx(tmp_path / "payroll" / "week.xlsx", b"data")
        h = compute_file_hash(f)
        conn = _db()
        conn.execute(
            "INSERT INTO ingested_files (id, filename, file_type, file_hash, row_count) "
            "VALUES (nextval('seq_ingested_files'), 'week.xlsx', 'payroll', ?, 5)",
            [h]
        )
        files = scan_input_dir(tmp_path, conn)
        assert files[0].status == "Ingested"


class TestArchiveFile:
    def test_file_moved(self, tmp_path):
        """Source file is removed; archive dir contains the moved file."""
        src = _make_xlsx(tmp_path / "src" / "payroll.xlsx")
        archive = tmp_path / "archive"
        dest = archive_file(src, archive)
        assert not src.exists()
        assert dest.exists() and dest.parent == archive

    def test_creates_archive_dir(self, tmp_path):
        """archive_file creates the archive directory if it does not exist."""
        src = _make_xlsx(tmp_path / "src" / "p.xlsx")
        archive = tmp_path / "new_archive"
        assert not archive.exists()
        archive_file(src, archive)
        assert archive.exists()

    def test_rename_on_conflict(self, tmp_path):
        """Two files with the same name are both preserved under different names."""
        src1 = _make_xlsx(tmp_path / "s1" / "payroll.xlsx", b"v1")
        src2 = _make_xlsx(tmp_path / "s2" / "payroll.xlsx", b"v2")
        archive = tmp_path / "archive"
        d1 = archive_file(src1, archive)
        d2 = archive_file(src2, archive)
        assert d1.exists() and d2.exists() and d1 != d2

    def test_returns_path_object(self, tmp_path):
        """Return value is a Path pointing to the archived file."""
        src = _make_xlsx(tmp_path / "src" / "r.xlsx")
        dest = archive_file(src, tmp_path / "archive")
        assert isinstance(dest, Path) and dest.exists()
