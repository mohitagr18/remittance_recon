"""
src/ui/pages/3_Name_Match_Manager.py
Settings — Name Match table management and Copay list.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd



from src.ui.styles.theme import inject_css
from src.ui.components.filters import _get_conn
from src.db import queries

inject_css()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>⚙️ Name Match Manager</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Manage payroll ↔ remittance name mappings and the copay client list.
            Changes persist to DuckDB and take effect on next ETL run.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()

tab_nm, tab_copay = st.tabs(["📋 Name Match Table", "💊 Copay List"])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: Name Match
# ═══════════════════════════════════════════════════════════════════════════
with tab_nm:
    nm_df = queries.get_name_match_table(conn)

    # ── Search / filter ──────────────────────────────────────────────────
    search = st.text_input("🔍 Search name match table", placeholder="Type payroll or remittance name...", key="nm_search")

    if search:
        mask = (
            nm_df["payroll_name"].str.contains(search, case=False, na=False)
            | nm_df["remittance_name"].fillna("").str.contains(search, case=False, na=False)
        )
        nm_display = nm_df[mask].copy()
    else:
        nm_display = nm_df.copy()

    # ── Highlight unmatched / not-available ──────────────────────────────
    unmatched = nm_display[nm_display["remittance_name"].isna() | (nm_display["remittance_name"] == "")]
    not_avail = nm_display[nm_display["remittance_name"] == "Not Available"]
    normal    = nm_display[~nm_display.index.isin(unmatched.index) & ~nm_display.index.isin(not_avail.index)]

    col_l, col_r = st.columns([3, 1])
    with col_l:
        st.markdown(
            f"<div class='info-banner'>"
            f"📊 {len(nm_df):,} total mappings · "
            f"<span style='color:#ef4444;font-weight:600;'>{len(unmatched)} unmatched</span> · "
            f"<span style='color:#8892a4;'>{len(not_avail)} not-available</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with col_r:
        show_unmatched_only = st.toggle("Show unmatched only", key="nm_show_unmatched")

    if show_unmatched_only:
        nm_display = unmatched

    display_cols = [c for c in ["id", "payroll_name", "remittance_name", "is_active", "updated_at"] if c in nm_display.columns]
    st.dataframe(
        nm_display[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "id":               st.column_config.NumberColumn("ID", width="small"),
            "payroll_name":     st.column_config.TextColumn("Payroll Name", width="large"),
            "remittance_name":  st.column_config.TextColumn("Remittance Name", width="large"),
            "is_active":        st.column_config.CheckboxColumn("Active", width="small"),
            "updated_at":       st.column_config.DatetimeColumn("Last Updated"),
        },
        key="nm_table",
    )

    # ── Add / Edit mapping ───────────────────────────────────────────────
    st.markdown(
        "<div class='section-header'><h3>✏️ Add or Update Mapping</h3></div>",
        unsafe_allow_html=True,
    )

    with st.form("nm_upsert_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            payroll_name = st.text_input(
                "Payroll Name",
                placeholder="e.g. Carroll, Robert PCA",
                key="nm_payroll_input",
            )
        with col2:
            remittance_name = st.text_input(
                "Remittance Name (leave blank for 'Not Available')",
                placeholder="e.g. Carroll, Robert",
                key="nm_rem_input",
            )
        submitted = st.form_submit_button("💾 Save Mapping", type="primary")
        if submitted:
            if not payroll_name.strip():
                st.error("Payroll name is required.")
            else:
                rem = remittance_name.strip() if remittance_name.strip() else "Not Available"
                queries.upsert_name_match(conn, payroll_name.strip(), rem)
                st.success(f"✅ Saved: **{payroll_name.strip()}** → **{rem}**")
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: Copay List
# ═══════════════════════════════════════════════════════════════════════════
with tab_copay:
    copay_df = queries.get_copay_table(conn)

    st.markdown(
        f"<div class='info-banner'>💊 {len(copay_df):,} clients with copay obligations</div>",
        unsafe_allow_html=True,
    )

    if copay_df.empty:
        st.info("No copay clients found.", icon="ℹ️")
    else:
        display_cols = [c for c in ["id", "client_name", "insurance", "is_active", "created_at"] if c in copay_df.columns]
        st.dataframe(
            copay_df[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id":          st.column_config.NumberColumn("ID", width="small"),
                "client_name": st.column_config.TextColumn("Client Name", width="large"),
                "insurance":   st.column_config.TextColumn("Insurance", width="medium"),
                "is_active":   st.column_config.CheckboxColumn("Active"),
                "created_at":  st.column_config.DatetimeColumn("Created At"),
            },
        )
