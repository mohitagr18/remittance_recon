"""
src/ui/components/filters.py
Shared filter widgets used across multiple pages.
"""
from __future__ import annotations

import streamlit as st

from src.db import queries
from src.db.connection import get_persistent_conn
from src.config import cfg


def _get_conn():
    """Return or create a persistent DB connection stored in session state."""
    if "db_conn" not in st.session_state:
        st.session_state.db_conn = get_persistent_conn(cfg.db_path)
    return st.session_state.db_conn


def week_filter(key: str = "week_filter") -> str | None:
    """Week picker — returns selected week_start_date string or None (all weeks)."""
    conn = _get_conn()
    weeks_df = queries.available_weeks(conn)
    if weeks_df.empty:
        st.sidebar.info("No weeks loaded yet.")
        return None

    options = ["All Weeks"] + [
        f"{row.week_start_date} → {row.week_end_date}"
        for _, row in weeks_df.iterrows()
    ]
    choice = st.sidebar.selectbox("📅 Week", options, key=key)
    if choice == "All Weeks":
        return None
    return choice.split(" → ")[0]


def insurance_filter(key: str = "ins_filter", multi: bool = False) -> str | None | list[str]:
    """Insurance picker. multi=True returns a list, else a single string or None."""
    conn = _get_conn()
    insurances = queries.available_insurances(conn)
    if not insurances:
        return [] if multi else None

    if multi:
        selected = st.sidebar.multiselect("🏥 Insurance", insurances, key=key)
        return selected if selected else []
    else:
        options = ["All"] + insurances
        choice = st.sidebar.selectbox("🏥 Insurance", options, key=key)
        return None if choice == "All" else choice


def result_filter(key: str = "result_filter") -> str | None:
    """Follow-up reason filter."""
    conn = _get_conn()
    reasons = queries.available_result_details(conn)
    if not reasons:
        return None
    options = ["All Reasons"] + reasons
    choice = st.sidebar.selectbox("⚠️ Reason", options, key=key)
    return None if choice == "All Reasons" else choice
