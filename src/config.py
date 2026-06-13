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
    input_dir: Path = field(default_factory=lambda: _resolve("INPUT_DIR", "input"))
    archive_dir: Path = field(default_factory=lambda: _resolve("ARCHIVE_DIR", "archive"))
    recon_file: Path = field(default_factory=lambda: _resolve("RECON_FILE", "input/Payroll-Billing-Remittance 02182026-02242026.xlsx"))

    # ── Database ──────────────────────────────────────────────────────────────
    db_path: Path = field(default_factory=lambda: _resolve("DB_PATH", "data/recon.duckdb"))

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))

    @property
    def payroll_file(self) -> Path:
        p = self.input_dir / "payroll"
        files = list(p.glob("*.xlsx"))
        if files:
            return files[0]
        # Try archive fallback
        archived = list(self.archive_dir.glob("EmpTimeCardReport*.xlsx"))
        if archived:
            return archived[0]
        return p / "EmpTimeCardReport - PY 03062026.xlsx"

    @property
    def remittance_file(self) -> Path:
        p = self.input_dir / "master_remit"
        files = list(p.glob("*.xlsx"))
        if files:
            return files[0]
        # Try archive fallback
        archived = list(self.archive_dir.glob("V*.xlsx")) + list(self.archive_dir.glob("*Remittance*.xlsx"))
        if archived:
            return archived[0]
        return p / "V5.1 2026 Remittance Report Master Updated 05052026.xlsx"

    def validate(self) -> None:
        """Raise if required directories or files are missing."""
        if not self.input_dir.exists():
            raise FileNotFoundError(f"INPUT_DIR not found: {self.input_dir}")
        if not self.recon_file.exists():
            raise FileNotFoundError(f"RECON_FILE not found: {self.recon_file}")
        # Ensure DB directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def _resolve(env_var: str, default: str) -> Path:
    raw = os.getenv(env_var, default)
    p = Path(raw)
    return p if p.is_absolute() else _ROOT / p


# ── Singleton ─────────────────────────────────────────────────────────────────
cfg = Config()
