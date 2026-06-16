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


def week_filter(key: str = "week_filter", show_archived: bool = True, in_sidebar: bool = True) -> str | None:
    """Week picker — returns selected week_start_date string or None (all weeks)."""
    import datetime
    import pandas as pd
    conn = _get_conn()
    weeks_df = queries.available_weeks(conn)
    if weeks_df.empty:
        widget = st.sidebar if in_sidebar else st
        widget.info("No weeks loaded yet.")
        return None

    if not show_archived:
        one_year_and_week_ago = (datetime.date.today() - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
        weeks_df = weeks_df[pd.to_datetime(weeks_df["week_start_date"]).dt.strftime("%Y-%m-%d") >= one_year_and_week_ago]

    # Sort ascending so that the list starts with the oldest week
    weeks_df = weeks_df.sort_values(by="week_start_date", ascending=True)

    label_to_date = {}
    options = ["All Weeks"]
    for _, row in weeks_df.iterrows():
        s_dt = pd.to_datetime(row.week_start_date)
        e_dt = pd.to_datetime(row.week_end_date)
        label = f"{s_dt.strftime('%b %d, %Y')} – {e_dt.strftime('%b %d, %Y')}"
        
        options.append(label)
        label_to_date[label] = s_dt.strftime("%Y-%m-%d")

    widget = st.sidebar if in_sidebar else st
    choice = widget.selectbox("📅 Week", options, key=key)
    if choice == "All Weeks":
        return None
    return label_to_date.get(choice)


def insurance_filter(key: str = "ins_filter", multi: bool = False, in_sidebar: bool = True) -> str | None | list[str]:
    """Insurance picker. multi=True returns a list, else a single string or None."""
    conn = _get_conn()
    insurances = queries.available_insurances(conn)
    if not insurances:
        return [] if multi else None

    widget = st.sidebar if in_sidebar else st
    if multi:
        selected = widget.multiselect("🏥 Insurance", insurances, key=key)
        return selected if selected else []
    else:
        options = ["All"] + insurances
        choice = widget.selectbox("🏥 Insurance", options, key=key)
        return None if choice == "All" else choice


def result_filter(key: str = "result_filter", in_sidebar: bool = True) -> str | None:
    """Follow-up reason filter."""
    conn = _get_conn()
    reasons = queries.available_result_details(conn)
    if not reasons:
        return None
    options = ["All Reasons"] + reasons
    widget = st.sidebar if in_sidebar else st
    choice = widget.selectbox("⚠️ Reason", options, key=key)
    return None if choice == "All Reasons" else choice
