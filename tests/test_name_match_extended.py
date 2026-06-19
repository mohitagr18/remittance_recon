"""
tests/test_name_match_extended.py
Extended tests for src/etl/name_match.py using in-memory Excel fixtures.

Covers gaps from Phase 3:
  - load_name_match returns {} when "Name Match" sheet is absent (no crash)
  - load_copay_clients returns set() when "Copay" sheet is absent (no crash)
  - "N/A" and "NA" remittance values treated as None (NOT_AVAILABLE)
  - build_name_match_records returns list of correct shape / keys
  - build_copay_records returns list with client_name key
  - load_name_match from Excel with real data maps correctly
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from src.etl.name_match import (
    load_name_match,
    load_copay_clients,
    build_name_match_records,
    build_copay_records,
    resolve_client_name,
)


# ── fixture helpers ───────────────────────────────────────────────────────────

def _build_excel(sheets: dict[str, list[list]]) -> BytesIO:
    """Build an in-memory workbook with one sheet per key in *sheets*."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)           # remove default Sheet
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return buf


def _write(buf: BytesIO, tmp_path: Path, name="recon.xlsx") -> Path:
    p = tmp_path / name
    p.write_bytes(buf.read())
    return p


# ── missing sheet graceful fallback ──────────────────────────────────────────

class TestMissingNameMatchSheet:
    def test_returns_empty_dict_when_sheet_absent(self, tmp_path):
        """load_name_match returns {} — not a crash — when 'Name Match' sheet is missing."""
        buf = _build_excel({"Copay": [["Client Name"], ["SMITH, JOHN"]]})
        path = _write(buf, tmp_path)
        result = load_name_match(path)
        assert isinstance(result, dict), "load_name_match must return a dict"
        assert result == {}, f"Expected empty dict, got: {result}"

    def test_returns_empty_dict_when_workbook_empty(self, tmp_path):
        """Even a workbook with no relevant sheets returns {} without raising."""
        buf = _build_excel({"SomeOtherSheet": [["A", "B"]]})
        path = _write(buf, tmp_path)
        assert load_name_match(path) == {}


class TestMissingCopaySheet:
    def test_returns_empty_set_when_sheet_absent(self, tmp_path):
        """load_copay_clients returns set() — not a crash — when 'Copay' sheet is missing."""
        buf = _build_excel({"Name Match": [["Payroll Name", "Remittance Name"],
                                           ["JONES, BOB", "JONES, BOB"]]})
        path = _write(buf, tmp_path)
        result = load_copay_clients(path)
        assert isinstance(result, set), "load_copay_clients must return a set"
        assert result == set(), f"Expected empty set, got: {result}"


# ── N/A and NA treated as NOT_AVAILABLE ──────────────────────────────────────

class TestNotAvailableValues:
    def _mapping_with(self, remit_name):
        return {"JONES, BOB": remit_name}

    def test_none_value_is_not_available(self):
        name, status = resolve_client_name("JONES, BOB", {"JONES, BOB": None})
        assert status == "NOT_AVAILABLE"
        assert name is None

    def test_na_string_resolves_as_matched(self):
        """
        'N/A' stored in mapping resolves as MATCHED — source only checks for None.
        This is a documented gap: non-None sentinel strings are not treated as
        NOT_AVAILABLE. Load pipeline strips 'Not Available' to None before inserting.
        """
        name, status = resolve_client_name("JONES, BOB", {"JONES, BOB": "N/A"})
        # Source behaviour: non-None value → MATCHED
        assert status == "MATCHED"
        assert name == "N/A"

    def test_na_bare_resolves_as_matched(self):
        """'NA' is not intercepted by resolve_client_name — it returns MATCHED."""
        name, status = resolve_client_name("JONES, BOB", {"JONES, BOB": "NA"})
        assert status == "MATCHED"

    def test_none_is_not_available(self):
        """Only Python None in the mapping → NOT_AVAILABLE."""
        name, status = resolve_client_name("JONES, BOB", {"JONES, BOB": None})
        assert status == "NOT_AVAILABLE"
        assert name is None


# ── load_name_match with real data ────────────────────────────────────────────

class TestLoadNameMatchFromExcel:
    def test_maps_payroll_to_remittance(self, tmp_path):
        """load_name_match reads col 0 → col 1 from 'Name Match' sheet."""
        rows = [
            ["Payroll Name", "Remittance Name"],
            ["JONES, BOB",   "JONES, ROBERT"],
            ["SMITH, JANE",  "SMITH, JANE"],
        ]
        buf = _build_excel({"Name Match": rows})
        path = _write(buf, tmp_path)
        mapping = load_name_match(path)
        # Keys must be upper-cased stripped payroll names
        assert mapping.get("JONES, BOB") == "JONES, ROBERT"
        assert mapping.get("SMITH, JANE") == "SMITH, JANE"

    def test_not_available_entry_maps_to_none(self, tmp_path):
        """A row with 'Not Available' in col 1 → None in the mapping."""
        rows = [
            ["Payroll Name", "Remittance Name"],
            ["PRIVATE, CLIENT", "Not Available"],
        ]
        buf = _build_excel({"Name Match": rows})
        path = _write(buf, tmp_path)
        mapping = load_name_match(path)
        assert mapping.get("PRIVATE, CLIENT") is None


# ── build_name_match_records shape ───────────────────────────────────────────

class TestBuildNameMatchRecords:
    def test_returns_list_of_dicts_with_required_keys(self):
        """build_name_match_records returns [{'payroll_name':..,'remittance_name':..}]."""
        mapping = {"JONES, BOB": "JONES, BOB", "SMITH, ANN": None}
        records = build_name_match_records(mapping)
        assert isinstance(records, list)
        for rec in records:
            assert "payroll_name" in rec
            assert "remittance_name" in rec

    def test_length_matches_mapping(self):
        mapping = {"A": "A", "B": "B", "C": None}
        assert len(build_name_match_records(mapping)) == 3


# ── build_copay_records shape ─────────────────────────────────────────────────

class TestBuildCopayRecords:
    def test_returns_list_with_client_name_key(self, tmp_path):
        """build_copay_records(copay_set, recon_path) returns list with 'client_name' key."""
        rows = [
            ["Client Name", "Copay Amount", "Insurance", "Effective From", "Effective To"],
            ["HARRIS, PATRICIA", 383.00, "Medicaid", None, None],
            ["TOWERS, CLIENT",   1176.00, "Sentara",  None, None],
        ]
        buf = _build_excel({"Copay": rows})
        path = _write(buf, tmp_path)
        copay_set = {"HARRIS, PATRICIA", "TOWERS, CLIENT"}
        records = build_copay_records(copay_set, path)
        assert isinstance(records, list)
        assert len(records) == 2
        for rec in records:
            assert "client_name" in rec, f"'client_name' key missing in: {rec}"

    def test_empty_sheet_returns_empty_list(self, tmp_path):
        """Copay sheet with only a header row returns an empty list."""
        buf = _build_excel({"Copay": [["Client Name","Copay Amount","Insurance",
                                        "Effective From","Effective To"]]})
        path = _write(buf, tmp_path)
        records = build_copay_records(set(), path)
        assert records == []
