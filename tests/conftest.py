"""Shared fixtures for test suite."""

from pathlib import Path

import pytest

from src.db.connection import get_persistent_conn


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """Run the pipeline once and reuse for all tests."""
    from src.etl.pipeline import run_pipeline
    from src.config import cfg

    db = tmp_path_factory.mktemp("data") / "test.duckdb"
    run_pipeline(
        db_path=db,
        payroll_path=cfg.payroll_file,
        remittance_path=cfg.remittance_file,
    )
    return db


@pytest.fixture(scope="session")
def conn(db_path):
    """Persistent read-only connection for query tests."""
    c = get_persistent_conn(db_path)
    yield c
    c.close()


@pytest.fixture(scope="session")
def conn_with_copay(db_path):
    """Connection with copay amounts seeded for copay query tests."""
    from src.db.connection import get_persistent_conn
    c = get_persistent_conn(db_path)

    for sql in [
        "ALTER TABLE copay_clients ADD COLUMN IF NOT EXISTS copay_amount DECIMAL(10,2)",
        "ALTER TABLE copay_clients ADD COLUMN IF NOT EXISTS effective_from DATE",
        "ALTER TABLE copay_clients ADD COLUMN IF NOT EXISTS effective_to DATE",
        "ALTER TABLE copay_clients ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]:
        c.execute(sql)

    copay_data = [
        ("BUTTS, SHIRLEY",           153.00),
        ("CLAIBORNE, GEORGE",        535.00),
        ("JARRETT, VICTORIA",         19.00),
        ("MASSENBURG, KATHERINE",    397.26),
        ("COCHRAN, TELEECA",         144.41),
        ("RICHEY, MICHAH",           749.00),
        ("STOKES, SR, SHYRONNE",     249.00),
        ("BUTLER, JANNIE",           643.59),
        ("BERRYMAN, SHELIAH",        383.00),
        ("CLAYTON, RALPH",           907.95),
        ("PARKER, NORMA",            478.00),
        ("TOWERS, LINDA",           1176.00),
    ]
    for name, amount in copay_data:
        c.execute(
            "UPDATE copay_clients SET copay_amount = ?, updated_at = CURRENT_TIMESTAMP WHERE client_name = ?",
            [amount, name]
        )

    max_id = c.execute("SELECT COALESCE(MAX(id), 0) FROM copay_clients").fetchone()[0]
    new_clients = [
        (max_id + 1, "PEEBLES, LUCY",           174.14),
        (max_id + 2, "TRISTVAN-BOTTE, VIVIAN",   28.00),
    ]
    for id_, name, amount in new_clients:
        existing = c.execute(
            "SELECT COUNT(*) FROM copay_clients WHERE client_name = ?", [name]
        ).fetchone()[0]
        if existing == 0:
            c.execute(
                "INSERT INTO copay_clients (id, client_name, is_active, copay_amount, updated_at) "
                "VALUES (?, ?, TRUE, ?, CURRENT_TIMESTAMP)",
                [id_, name, amount]
            )

    yield c
    c.close()


@pytest.fixture(scope="session")
def conn_recon():
    """Read-only connection to the real recon.duckdb for copay monthly status tests."""
    import duckdb
    from pathlib import Path
    db = Path(__file__).parent.parent / "data" / "recon.duckdb"
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()
