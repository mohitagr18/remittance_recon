"""
src/config.py
Central configuration — loads .env, resolves paths, exposes a singleton Config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ── Locate project root (two levels above this file: src/ → root) ────────────
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


@dataclass
class Config:
    """All runtime settings resolved from environment variables."""

    # ── Source files ──────────────────────────────────────────────────────────
    payroll_file: Path = field(default_factory=lambda: _resolve("PAYROLL_FILE", "input/EmpTimeCardReport - PY 03062026.xlsx"))
    remittance_file: Path = field(default_factory=lambda: _resolve("REMITTANCE_FILE", "input/V5.1 2026 Remittance Report Master Updated 05052026.xlsx"))
    recon_file: Path = field(default_factory=lambda: _resolve("RECON_FILE", "input/Payroll-Billing-Remittance 02182026-02242026.xlsx"))

    # ── Database ──────────────────────────────────────────────────────────────
    db_path: Path = field(default_factory=lambda: _resolve("DB_PATH", "data/recon.duckdb"))

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))

    def validate(self) -> None:
        """Raise if required files are missing."""
        for name, path in [
            ("PAYROLL_FILE", self.payroll_file),
            ("REMITTANCE_FILE", self.remittance_file),
            ("RECON_FILE", self.recon_file),
        ]:
            if not path.exists():
                raise FileNotFoundError(f"{name} not found: {path}")
        # Ensure DB directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def _resolve(env_var: str, default: str) -> Path:
    raw = os.getenv(env_var, default)
    p = Path(raw)
    return p if p.is_absolute() else _ROOT / p


# ── Singleton ─────────────────────────────────────────────────────────────────
cfg = Config()
