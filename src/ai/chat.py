"""
src/ai/chat.py
Natural language → SQL → plain-English answer engine.
Supports OpenAI (GPT-4o) and Google Gemini based on LLM_PROVIDER env var.
"""
from __future__ import annotations

import re
import textwrap
from typing import Any

import duckdb
import pandas as pd

from src.ai.prompts import build_prompt
from src.config import cfg


# ── LLM call ──────────────────────────────────────────────────────────────


def _call_openai(messages: list[dict]) -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=cfg.openai_api_key)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0,
        max_tokens=512,
    )
    return resp.choices[0].message.content.strip()


def _call_gemini(messages: list[dict]) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=cfg.google_api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")
    # Flatten messages into a single prompt for Gemini
    prompt = "\n\n".join(m["content"] for m in messages)
    resp = model.generate_content(prompt)
    return resp.text.strip()


def _extract_sql(raw: str) -> str:
    """Extract bare SQL from LLM response (strips markdown fences if present)."""
    # Strip ```sql ... ``` or ``` ... ```
    match = re.search(r"```(?:sql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return raw.strip()


# ── Main chat function ─────────────────────────────────────────────────────


def ask(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    max_rows: int = 50,
) -> dict[str, Any]:
    """
    Ask a natural language question and get a plain-English answer + DataFrame.

    Returns:
        {
            "sql": str,
            "df": pd.DataFrame,
            "answer": str,
            "error": str | None,
        }
    """
    result: dict[str, Any] = {"sql": "", "df": pd.DataFrame(), "answer": "", "error": None}

    try:
        messages = build_prompt(question)

        if cfg.llm_provider.lower() == "gemini":
            raw = _call_gemini(messages)
        else:
            raw = _call_openai(messages)

        sql = _extract_sql(raw)
        result["sql"] = sql

        # Safety: only allow SELECT
        first_word = sql.lstrip().split()[0].upper() if sql.strip() else ""
        if first_word not in ("SELECT", "WITH"):
            raise ValueError(f"Non-SELECT query rejected: {first_word}")

        df = conn.execute(sql).df().head(max_rows)
        result["df"] = df
        result["answer"] = _format_answer(question, df)

    except Exception as exc:
        result["error"] = str(exc)
        result["answer"] = f"⚠️ Sorry, I couldn't answer that: {exc}"

    return result


# ── Answer formatter ───────────────────────────────────────────────────────


def _format_answer(question: str, df: pd.DataFrame) -> str:
    """Convert a DataFrame result into a plain-English summary."""
    if df.empty:
        return "No results found for that question."

    nrows, ncols = df.shape

    # Single-cell scalar
    if nrows == 1 and ncols == 1:
        val = df.iloc[0, 0]
        col = df.columns[0]
        return f"**{col.replace('_', ' ').title()}**: {_fmt_val(val)}"

    # Single row
    if nrows == 1:
        parts = [f"**{c.replace('_', ' ').title()}**: {_fmt_val(df.iloc[0][c])}" for c in df.columns]
        return "  \n".join(parts)

    # Multi-row: summarize
    lines = [f"Found **{nrows}** result(s):"]
    for _, row in df.head(10).iterrows():
        parts = [f"{c.replace('_', ' ').title()}: {_fmt_val(row[c])}" for c in df.columns]
        lines.append("• " + " · ".join(parts))
    if nrows > 10:
        lines.append(f"*(and {nrows - 10} more…)*")
    return "  \n".join(lines)


def _fmt_val(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if isinstance(val, float):
        if val > 1000:
            return f"{val:,.1f}"
        return f"{val:.2f}"
    return str(val)
