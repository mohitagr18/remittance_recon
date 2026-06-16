"""
src/ui/pages/2_Analyst_Workbench.py
Billing Analyst Workbench — follow-up queue with action buttons and rebill tracker.
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
from src.ui.components.filters import week_filter, insurance_filter, result_filter, _get_conn
from src.db import queries

inject_css()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>🔧 Analyst Workbench</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Follow-up queue · Action buttons · Rebill tracker
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()

# ── Top-level filters ─────────────────────────────────────────────────────────
col_w, col_i, col_r, col_f, _ = st.columns([2.2, 1.5, 1.5, 1.0, 2.8])
with col_w:
    week = week_filter("wb_week", in_sidebar=False)
with col_i:
    ins = insurance_filter("wb_ins", in_sidebar=False)
with col_r:
    reason = result_filter("wb_reason", in_sidebar=False)
with col_f:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    fu_only = st.toggle("Follow-Up Only", value=True, key="wb_fu_only")

# ── Follow-Up Queue ─────────────────────────────────────────────────────────
st.markdown(
    "<div class='section-header'><h3>⚠️ Follow-Up Queue</h3></div>",
    unsafe_allow_html=True,
)

recon_df = queries.all_reconciliation(
    conn,
    week_start=week,
    insurance=ins,
    follow_up_only=fu_only,
)

if reason:
    recon_df = recon_df[recon_df["result_detailed"] == reason]

if recon_df.empty:
    st.success("✅ No items match the current filters.", icon="✅")
else:
    # ── Result badge coloring helper ────────────────────────────────────────
    def _result_color(val):
        if val == "Good":
            return "background-color: #14532d; color: #4ade80"
        if val == "Follow up":
            return "background-color: #451a03; color: #fb923c"
        return "color: #8892a4"

    display_cols = [c for c in [
        "id", "insurance", "client_name_payroll",
        "payroll_hours", "billed_hours", "paid_hours",
        "payroll_vs_billed", "billing_vs_paid",
        "result_simple", "result_detailed",
        "yash_comments", "connie_comments",
    ] if c in recon_df.columns]

    st.info(
        f"**{len(recon_df):,}** items in queue  ·  "
        f"Filters: week={week or 'All'}, ins={ins or 'All'}, reason={reason or 'All'}",
        icon="📋",
    )

    # Action buttons at top
    col_act1, col_act2, col_spacer = st.columns([1, 1, 4])
    with col_act1:
        mark_reviewed = st.button("✅ Mark Selected Reviewed", key="btn_mark_reviewed", type="secondary")
    with col_act2:
        send_rebill = st.button("🔄 Send Selected to Rebill", key="btn_send_rebill", type="primary")

    # Row selection table
    selection = st.dataframe(
        recon_df[display_cols],
        use_container_width=True,
        hide_index=True,
        height=450,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "id":                 st.column_config.NumberColumn("ID",         width="small"),
            "insurance":          st.column_config.TextColumn("Insurance",    width="small"),
            "client_name_payroll":st.column_config.TextColumn("Client",       width="medium"),
            "payroll_hours":      st.column_config.NumberColumn("Payroll",    format="%.1f"),
            "billed_hours":       st.column_config.NumberColumn("Billed",     format="%.1f"),
            "paid_hours":         st.column_config.NumberColumn("Paid",       format="%.1f"),
            "payroll_vs_billed":  st.column_config.NumberColumn("PvB Δ",      format="%.1f"),
            "billing_vs_paid":    st.column_config.NumberColumn("BvP Δ",      format="%.1f"),
            "result_simple":      st.column_config.TextColumn("Status",       width="small"),
            "result_detailed":    st.column_config.TextColumn("Reason",       width="medium"),
            "yash_comments":      st.column_config.TextColumn("Yash Notes",   width="medium"),
            "connie_comments":    st.column_config.TextColumn("Connie Notes", width="medium"),
        },
        key="wb_table",
    )

    selected_rows = selection.selection.rows if selection.selection else []

    # ── Handle actions ──────────────────────────────────────────────────────
    if mark_reviewed and selected_rows:
        ids = recon_df.iloc[selected_rows]["id"].tolist()
        for rid in ids:
            queries.mark_reviewed(conn, int(rid))
        st.success(f"✅ Marked {len(ids)} item(s) as reviewed.", icon="✅")
        st.rerun()

    if send_rebill and selected_rows:
        ids = recon_df.iloc[selected_rows]["id"].tolist()
        for rid in ids:
            queries.add_rebill_item(conn, reconciliation_id=int(rid))
        st.success(f"🔄 {len(ids)} item(s) added to rebill queue.", icon="🔄")
        st.rerun()

    if selected_rows:
        st.markdown(
            f"<div class='info-banner'>ℹ️ {len(selected_rows)} row(s) selected · Use action buttons above</div>",
            unsafe_allow_html=True,
        )

# ── Rebill Tracker ──────────────────────────────────────────────────────────
st.markdown(
    "<div class='section-header'><h3>🔄 Rebill Tracker</h3></div>",
    unsafe_allow_html=True,
)

rebill_df = queries.get_rebill_items(conn)

if rebill_df.empty:
    st.markdown(
        "<div class='info-banner'>No rebill items yet. Select rows above and click 'Send to Rebill'.</div>",
        unsafe_allow_html=True,
    )
else:
    # Status color map
    STATUS_COLORS = {
        "PENDING":   "🟡",
        "SUBMITTED": "🔵",
        "PAID":      "🟢",
        "DENIED":    "🔴",
    }

    # Format date range into one readable column starting with YYYY-MM-DD for chronological sorting
    rebill_df["week_range"] = (
        pd.to_datetime(rebill_df["week_start_date"]).dt.strftime("%Y-%m-%d")
        + " ("
        + pd.to_datetime(rebill_df["week_start_date"]).dt.strftime("%b %d")
        + " – "
        + pd.to_datetime(rebill_df["week_end_date"]).dt.strftime("%b %d")
        + ")"
    )

    display_cols = [c for c in [
        "id", "insurance", "client_name_payroll", "week_range",
        "tcn", "denial_code", "rebill_date", "status", "notes", "created_at",
    ] if c in rebill_df.columns]

    rebill_df["status"] = rebill_df["status"].apply(
        lambda s: f"{STATUS_COLORS.get(s, '')} {s}" if isinstance(s, str) else s
    )

    st.dataframe(
        rebill_df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "id":                   st.column_config.NumberColumn("ID", width="small"),
            "insurance":            st.column_config.TextColumn("Insurance", width="small"),
            "client_name_payroll":  st.column_config.TextColumn("Client", width="medium"),
            "week_range":           st.column_config.TextColumn("Week", width="medium"),
            "tcn":                  st.column_config.TextColumn("TCN"),
            "denial_code":          st.column_config.TextColumn("Denial Code"),
            "rebill_date":          st.column_config.DateColumn("Rebill Date"),
            "status":               st.column_config.TextColumn("Status"),
            "notes":                st.column_config.TextColumn("Notes"),
            "created_at":           st.column_config.DatetimeColumn("Created At"),
        },
    )
    st.caption(f"{len(rebill_df):,} rebill item(s) tracked")
