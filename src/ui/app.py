"""
src/ui/app.py
Streamlit entry point — COO Executive Dashboard (default landing page).
Run with: streamlit run src/ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Recon Dashboard",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "Payroll-Billing-Remittance Reconciliation · Phase 1"},
)

from src.ui.styles.theme import inject_css
from src.ui.components.kpi_cards import render_kpi_row
from src.ui.components.charts import rolling_trend_chart, followup_donut, payer_bar_chart
from src.ui.components.filters import week_filter, insurance_filter, _get_conn
from src.db import queries

inject_css()

# ── Sidebar ────────────────────────────────────────────────────────────────
st.sidebar.markdown(
    """
    <div style='padding:16px 0 8px;'>
        <div style='font-size:1.15rem;font-weight:700;color:#e8eaf0;'>💰 ReconApp</div>
        <div style='font-size:0.72rem;color:#8892a4;margin-top:2px;'>Billing Reconciliation Platform</div>
    </div>
    <hr style='border-color:#1e2130;margin:8px 0 16px;'/>
    """,
    unsafe_allow_html=True,
)
st.sidebar.markdown("**Filters**")
week      = week_filter("dash_week")
insurance = insurance_filter("dash_ins")

# ── Page header ────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>
            📊 COO Executive Dashboard
        </h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Weekly payroll-billing-remittance reconciliation summary
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()

# ── KPI Cards ──────────────────────────────────────────────────────────────
summary = queries.weekly_summary(conn, week_start=week, insurance=insurance)

if summary.empty or summary.iloc[0]["total_clients"] == 0:
    st.info("⚡ No reconciliation data loaded yet. Run the ETL pipeline first.", icon="ℹ️")
    st.code("python -m src.etl.pipeline", language="bash")
    st.stop()

row            = summary.iloc[0]
total_clients  = int(row.get("total_clients", 0) or 0)
billed_hrs     = float(row.get("total_billed_hrs", 0) or 0)
paid_hrs       = float(row.get("total_paid_hrs", 0) or 0)
pending_hrs    = float(row.get("pending_hrs", 0) or 0)
followup_count = int(row.get("followup_count", 0) or 0)
rate           = float(row.get("collection_rate_pct", 0) or 0)

render_kpi_row([
    {"label": "Total Clients",   "value": f"{total_clients:,}",  "sub": "in reconciliation",  "color": "blue"},
    {"label": "Billed Hours",    "value": f"{billed_hrs:,.1f}",  "sub": "hrs submitted",       "color": "purple"},
    {"label": "Paid Hours",      "value": f"{paid_hrs:,.1f}",    "sub": "hrs collected",       "color": "green"},
    {"label": "Pending Hours",   "value": f"{pending_hrs:,.1f}", "sub": "billed − paid",       "color": "yellow"},
    {"label": "Follow-Ups",      "value": str(followup_count),   "sub": "need attention",      "color": "red"},
    {"label": "Collection Rate", "value": f"{rate:.1f}%",        "sub": "target ≥ 95%",        "color": "green" if rate >= 95 else "red"},
])

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Row 1: Rolling trend + Follow-up donut ─────────────────────────────────
col_left, col_right = st.columns([3, 2], gap="large")

with col_left:
    st.markdown(
        "<div class='section-header'><h3>📈 12-Week Rolling Trend</h3></div>",
        unsafe_allow_html=True,
    )
    trend_df = queries.rolling_trend(conn, weeks=12, insurance=insurance)
    st.plotly_chart(rolling_trend_chart(trend_df), width="stretch", config={"displayModeBar": False})

with col_right:
    st.markdown(
        "<div class='section-header'><h3>🔍 Follow-Up Breakdown</h3></div>",
        unsafe_allow_html=True,
    )
    reason_df = queries.followup_reason_breakdown(conn, week_start=week, insurance=insurance)
    st.plotly_chart(followup_donut(reason_df), width="stretch", config={"displayModeBar": False})

# ── Row 2: Top Follow-Up Clients (deduplicated) ────────────────────────────
st.markdown(
    "<div class='section-header'><h3>⚠️ Top Follow-Up Clients</h3></div>",
    unsafe_allow_html=True,
)

top_fu = queries.top_followup_clients(conn, week_start=week, insurance=insurance, limit=15)

if top_fu.empty:
    st.success("✅ No follow-ups for the selected filters!", icon="✅")
else:
    # Build a formatted display dataframe
    display = top_fu.copy()
    display["date_range"] = (
        pd.to_datetime(display["week_start"]).dt.strftime("%b %d")
        + " – "
        + pd.to_datetime(display["week_end"]).dt.strftime("%b %d, %Y")
    )

    show_cols = ["insurance", "client", "date_range",
                 "payroll_hours", "billed_hours", "paid_hours",
                 "pending_hrs", "payroll_vs_billed", "reason"]
    show_cols = [c for c in show_cols if c in display.columns]

    st.caption(f"Showing top {len(display)} follow-up clients · 1 row per client · sorted by pending hrs ↓")
    st.dataframe(
        display[show_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "insurance":         st.column_config.TextColumn("Insurance",     width="small"),
            "client":            st.column_config.TextColumn("Client",        width="medium"),
            "date_range":        st.column_config.TextColumn("Week",          width="medium"),
            "payroll_hours":     st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
            "billed_hours":      st.column_config.NumberColumn("Billed Hrs",  format="%.1f"),
            "paid_hours":        st.column_config.NumberColumn("Paid Hrs",    format="%.1f"),
            "pending_hrs":       st.column_config.NumberColumn("⏳ Pending",  format="%.1f"),
            "payroll_vs_billed": st.column_config.NumberColumn("PvB Δ",       format="%.1f"),
            "reason":            st.column_config.TextColumn("Reason",        width="medium"),
        },
    )

# ── Row 3: Payer Collection Rates ──────────────────────────────────────────
st.markdown(
    "<div class='section-header'><h3>🏥 Payer Collection Rates</h3></div>",
    unsafe_allow_html=True,
)
payer_df = queries.payer_collection_rates(conn, week_start=week)
st.plotly_chart(payer_bar_chart(payer_df), width="stretch", config={"displayModeBar": False})
