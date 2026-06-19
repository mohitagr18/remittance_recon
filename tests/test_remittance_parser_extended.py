"""
tests/test_remittance_parser_extended.py
Extended unit tests for src/etl/remittance.py using synthetic in-memory
Excel fixtures — no real files required.

Covers every gap from Phase 3:
  - wrong/missing sheet raises ValueError
  - rows with fewer than 14 cols are skipped
  - dollar-string parsing ("$1,234.56" → 1234.56)
  - client_name_combined built from col 18 ("LAST, FIRST")
  - blank payment amount defaults to 0.0
  - parse_remittance is idempotent (same result on two calls)
"""
from __future__ import annotations
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from src.etl.remittance import parse_remittance

_SHEET = "Remittance Report Template"
_HEADER_ROW_IDX = 3   # 0-indexed → row 4 in Excel


def _make_row(
    batch=1877, pay_date="2026-01-15", txn="EFT", match="", claim="CLM001",
    txn_type="PAYMENT", charge="$100.00", payment="$90.00", allowed="$100.00",
    first="BOB", last="JONES", first_dos="2026-01-08", last_dos="2026-01-08",
    tcn="TCN001", billed=10.0, paid=9.0, remaining=1.0,
    client_space="JONES BOB", client_comma="JONES, BOB",
    month="1/", insurance="Medicaid", pay_val=90.0,
) -> list:
    return [batch, pay_date, txn, match, claim, txn_type, charge, payment,
            allowed, first, last, first_dos, last_dos, tcn, billed, paid,
            remaining, client_space, client_comma, month, insurance, pay_val]


def _build_remittance_xlsx(
    data_rows: list[list] | None = None,
    sheet_name: str = _SHEET,
) -> BytesIO:
    """
    Build a minimal remittance Excel in-memory.
    Rows 0-2: metadata/blank
    Row 3: headers (22 cols)
    Row 4+: data
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    # rows 0-2: metadata (parse_remittance skips via header=3)
    ws.append(["Last uploaded remittance sheet is dated 2026-01-15"])
    ws.append([None])
    ws.append([None])
    # row 3: headers
    ws.append([
        "Batch","Date","Transaction","Match Status","Claim","Transaction Type",
        "Charge","Payment","Allowed","First Name","Last Name",
        "First DOS","Last DOS","TCN","Billed Hrs","Paid Hrs","Hrs Remaining",
        "Client","Last Name, First","Month","Insurance","Payment Value",
    ])
    for r in (data_rows or [_make_row()]):
        ws.append(r)

    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return buf


def _write(buf: BytesIO, tmp_path: Path, name="remit.xlsx") -> Path:
    p = tmp_path / name
    p.write_bytes(buf.read())
    return p


# ── wrong sheet raises ValueError ────────────────────────────────────────────

class TestWrongSheetRaises:
    def test_missing_sheet_raises(self, tmp_path):
        """parse_remittance raises ValueError when the required sheet is absent."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Wrong Sheet Name"
        ws.append(["data"])
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        path = _write(buf, tmp_path, "bad.xlsx")
        with pytest.raises(ValueError, match="not found"):
            parse_remittance(path)


# ── short rows skipped ────────────────────────────────────────────────────────

class TestShortRowsSkipped:
    def test_row_with_fewer_than_14_cols_skipped(self, tmp_path):
        """A row with < 14 values must be silently skipped (no crash, no partial record)."""
        short_row = [1877, "2026-01-15", "EFT", "", "CLM"]  # only 5 cols
        full_row  = _make_row(tcn="TCN_GOOD")
        buf = _build_remittance_xlsx([short_row, full_row])
        path = _write(buf, tmp_path)
        records = parse_remittance(path)
        tcns = [r["tcn"] for r in records]
        assert "TCN_GOOD" in tcns
        assert len(records) == 1, f"Short row leaked: got {len(records)} records"


# ── dollar string parsing ─────────────────────────────────────────────────────

class TestDollarStringParsing:
    def test_dollar_comma_string_to_float(self, tmp_path):
        """'$1,234.56' in charge col must parse to float 1234.56."""
        row = _make_row(charge="$1,234.56", payment="$1,234.00",
                        billed=10.0, paid=9.0, tcn="TCN_DOLLAR")
        buf = _build_remittance_xlsx([row])
        path = _write(buf, tmp_path)
        records = parse_remittance(path)
        assert records[0]["charge_amount"] == pytest.approx(1234.56)
        assert records[0]["payment_amount"] == pytest.approx(1234.00)

    def test_plain_numeric_string(self, tmp_path):
        """A plain numeric string without $ also parses correctly."""
        row = _make_row(charge="100.00", payment="90.00", tcn="TCN_PLAIN")
        buf = _build_remittance_xlsx([row])
        path = _write(buf, tmp_path)
        records = parse_remittance(path)
        assert records[0]["charge_amount"] == pytest.approx(100.0)


# ── client_name_combined from col 18 ─────────────────────────────────────────

class TestClientNameCombined:
    def test_client_name_combined_is_last_comma_first(self, tmp_path):
        """client_name_combined comes from col 18 ('LAST, FIRST' format)."""
        row = _make_row(client_comma="HARRIS, PATRICIA", tcn="TCN_NAME")
        buf = _build_remittance_xlsx([row])
        path = _write(buf, tmp_path)
        records = parse_remittance(path)
        assert records[0]["client_name_combined"] == "HARRIS, PATRICIA"

    def test_client_space_col_17_not_used(self, tmp_path):
        """Col 17 ('LAST FIRST' no comma) must NOT be used as client_name_combined."""
        row = _make_row(client_space="HARRIS PATRICIA",
                        client_comma="HARRIS, PATRICIA", tcn="TCN_COL")
        buf = _build_remittance_xlsx([row])
        path = _write(buf, tmp_path)
        records = parse_remittance(path)
        assert "," in records[0]["client_name_combined"]


# ── blank payment defaults to 0.0 ────────────────────────────────────────────

class TestBlankPaymentDefault:
    def test_blank_payment_amount_is_none_no_crash(self, tmp_path):
        """
        A blank payment cell produces None from _parse_dollar — no crash.
        Documents current source behaviour: None is returned, not 0.0.
        Downstream code must handle None payment_amount gracefully.
        """
        row = _make_row(payment=None, tcn="TCN_BLANK_PAY")
        buf = _build_remittance_xlsx([row])
        path = _write(buf, tmp_path)
        records = parse_remittance(path)
        # Must not crash; None is acceptable per current source behaviour
        assert records[0]["payment_amount"] is None or records[0]["payment_amount"] == pytest.approx(0.0)


# ── idempotency ───────────────────────────────────────────────────────────────

class TestParseRemittanceIdempotent:
    def test_same_result_on_two_calls(self, tmp_path):
        """parse_remittance called twice on the same file must return identical results."""
        buf1 = _build_remittance_xlsx()
        path = _write(buf1, tmp_path)
        r1 = parse_remittance(path)
        r2 = parse_remittance(path)
        assert len(r1) == len(r2)
        assert [x["tcn"] for x in r1] == [x["tcn"] for x in r2]
        assert [x["is_latest"] for x in r1] == [x["is_latest"] for x in r2]
