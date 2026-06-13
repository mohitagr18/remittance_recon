"""
src/ui/pages/0_Weekly_Recon.py
Weekly Reconciliation — Excel-style view.
For a selected week: one row per client, payroll/billed/paid/pending hours,
sorted by pending hours descending (largest shortfall first).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Weekly Recon",
    page_icon="📋",
    layout="wide",
)

from src.ui.styles.theme import inject_css
from src.ui.components.filters import week_filter, insurance_filter, _get_conn
from src.db import queries

inject_css()

conn = _get_conn()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>
            📋 Weekly Reconciliation
        </h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Excel-style view · one row per client · payroll vs billed vs paid · sorted by pending ↓
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar filters ─────────────────────────────────────────────────────────
st.sidebar.markdown("**Filters**")
week    = week_filter("wr_week")
ins     = insurance_filter("wr_ins")
fu_only = st.sidebar.toggle("Follow-Up Only", value=False, key="wr_fu_only")

# ── Load data ───────────────────────────────────────────────────────────────
df = queries.weekly_recon_detail(
    conn,
    week_start=week,
    insurance=ins if ins else None,
    follow_up_only=fu_only,
)

if df.empty:
    st.info("No reconciliation data for the selected filters. Run the ETL pipeline or adjust filters.", icon="ℹ️")
    st.stop()

# ── Summary bar ─────────────────────────────────────────────────────────────
total_payroll = df["payroll_hours"].sum()
total_billed  = df["billed_hours"].sum()
total_paid    = df["paid_hours"].sum()
total_pending = df["pending_hrs"].sum()
n_followup    = (df["status"] == "Follow up").sum()
n_good        = (df["status"] == "Good").sum()

# Show week range if a specific week is selected
if not df.empty and "week_start" in df.columns:
    ws = pd.to_datetime(df["week_start"].iloc[0]).strftime("%b %d")
    we = pd.to_datetime(df["week_end"].iloc[0]).strftime("%b %d, %Y")
    week_label = f"{ws} – {we}"
else:
    week_label = "All Weeks"

st.markdown(
    f"""
    <div style='background:linear-gradient(135deg,#1e2130,#252840);
                border:1px solid #2a2d3e;border-radius:12px;
                padding:16px 24px;margin-bottom:1.2rem;
                display:flex;gap:32px;flex-wrap:wrap;align-items:center;'>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Period</div>
            <div style='font-size:1rem;font-weight:700;color:#4f8ef7;margin-top:2px;'>{week_label}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Clients</div>
            <div style='font-size:1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{len(df):,}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Payroll Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{total_payroll:,.1f}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Billed Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#a78bfa;margin-top:2px;'>{total_billed:,.1f}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Paid Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#22c55e;margin-top:2px;'>{total_paid:,.1f}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>⏳ Pending Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#f59e0b;margin-top:2px;'>{total_pending:,.1f}</div>
        </div>
        <div style='margin-left:auto;display:flex;gap:16px;'>
            <div style='text-align:center;'>
                <div style='font-size:1.2rem;font-weight:700;color:#22c55e;'>{n_good}</div>
                <div style='font-size:0.68rem;color:#8892a4;'>✅ Good</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:1.2rem;font-weight:700;color:#f59e0b;'>{n_followup}</div>
                <div style='font-size:0.68rem;color:#8892a4;'>⚠️ Follow-up</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Build display columns ───────────────────────────────────────────────────
display = df.copy()

# Format date range into one readable column
display["week_range"] = (
    pd.to_datetime(display["week_start"]).dt.strftime("%b %d")
    + " – "
    + pd.to_datetime(display["week_end"]).dt.strftime("%b %d")
)

show_cols = [
    "insurance", "client", "week_range",
    "payroll_hours", "billed_hours", "paid_hours",
    "pending_hrs", "payroll_vs_billed",
    "status", "reason",
    "is_copay_client", "yash_comments", "connie_comments",
]
show_cols = [c for c in show_cols if c in display.columns]

# ── Status colour indicator column ─────────────────────────────────────────
STATUS_ICON = {"Good": "✅", "Follow up": "⚠️", "No Payroll Hours": "⬜"}
display["status"] = display["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}" if isinstance(s, str) else s)

# ── Render table ────────────────────────────────────────────────────────────
st.dataframe(
    display[show_cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "insurance":         st.column_config.TextColumn("Insurance",    width="small"),
        "client":            st.column_config.TextColumn("Client",       width="medium"),
        "week_range":        st.column_config.TextColumn("Week",         width="medium"),
        "payroll_hours":     st.column_config.NumberColumn("Payroll Hrs",format="%.1f"),
        "billed_hours":      st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
        "paid_hours":        st.column_config.NumberColumn("Paid Hrs",   format="%.1f"),
        "pending_hrs":       st.column_config.NumberColumn("⏳ Pending", format="%.1f"),
        "payroll_vs_billed": st.column_config.NumberColumn("PvB Δ",      format="%.1f"),
        "status":            st.column_config.TextColumn("Status",       width="small"),
        "reason":            st.column_config.TextColumn("Reason",       width="medium"),
        "is_copay_client":   st.column_config.CheckboxColumn("Copay",    width="small"),
        "yash_comments":     st.column_config.TextColumn("Yash Notes",   width="medium"),
        "connie_comments":   st.column_config.TextColumn("Connie Notes", width="medium"),
    },
    height=min(60 + len(display) * 35, 700),
)

st.caption(
    f"📊 {len(display):,} clients · sorted by ⏳ Pending hrs ↓ · "
    f"PvB Δ = Payroll vs Billed difference"
)

# ── Totals row ──────────────────────────────────────────────────────────────
st.markdown(
    f"""
    <div style='background:#13151f;border:1px solid #2a2d3e;border-radius:8px;
                padding:12px 20px;margin-top:8px;font-size:0.82rem;
                display:flex;gap:32px;flex-wrap:wrap;'>
        <span style='color:#8892a4;font-weight:600;text-transform:uppercase;letter-spacing:.06em;'>TOTALS</span>
        <span>Payroll: <b style='color:#e8eaf0;'>{total_payroll:,.1f}</b></span>
        <span>Billed: <b style='color:#a78bfa;'>{total_billed:,.1f}</b></span>
        <span>Paid: <b style='color:#22c55e;'>{total_paid:,.1f}</b></span>
        <span>Pending: <b style='color:#f59e0b;'>{total_pending:,.1f}</b></span>
        <span>PvB Δ: <b style='color:#e8eaf0;'>{(total_payroll - total_billed):,.1f}</b></span>
    </div>
    """,
    unsafe_allow_html=True,
)
