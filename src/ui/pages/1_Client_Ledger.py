"""
src/ui/pages/1_Client_Ledger.py
Client Ledger — full payment history per client.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Client Ledger", page_icon="📒", layout="wide")

import importlib
from src.ui.styles.theme import inject_css

from src.ui.components import charts
importlib.reload(charts)
from src.ui.components.charts import client_billed_paid_chart

from src.ui.components.filters import _get_conn

from src.db import queries
importlib.reload(queries)


inject_css()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>📒 Client Ledger</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Full payment history and reconciliation summary per client
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()
clients = queries.all_clients(conn)

if not clients:
    st.info("No clients found. Run the ETL pipeline first.", icon="ℹ️")
    st.stop()

# ── Client selector ─────────────────────────────────────────────────────────
selected = st.selectbox(
    "🔍 Search / Select Client",
    options=clients,
    placeholder="Type to search...",
    key="ledger_client",
)

if not selected:
    st.stop()

# ── Summary card ────────────────────────────────────────────────────────────
summary_df = queries.client_summary(conn, selected)

if not summary_df.empty:
    row = summary_df.iloc[0]
    ins          = row.get("insurance", "—") or "—"
    ytd_billed   = float(row.get("ytd_billed_hrs", 0) or 0)
    ytd_paid     = float(row.get("ytd_paid_hrs", 0) or 0)
    ytd_payroll  = float(row.get("ytd_payroll_hrs", 0) or 0)
    total_weeks  = int(row.get("total_weeks", 0) or 0)
    fu_weeks     = int(row.get("followup_weeks", 0) or 0)
    rate         = float(row.get("collection_rate_pct", 0) or 0)

    st.markdown(
        f"""
        <div style='background:linear-gradient(135deg,#1e2130,#252840);border:1px solid #2a2d3e;
                    border-radius:12px;padding:20px 24px;margin-bottom:1.2rem;
                    display:flex;gap:40px;flex-wrap:wrap;align-items:center;'>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Client</div>
                <div style='font-size:1.1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{selected}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Insurance</div>
                <div style='font-size:1rem;font-weight:600;color:#4f8ef7;margin-top:2px;'>{ins}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>YTD Billed Hrs</div>
                <div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{ytd_billed:,.1f}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>YTD Paid Hrs</div>
                <div style='font-size:1rem;font-weight:600;color:#22c55e;margin-top:2px;'>{ytd_paid:,.1f}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Collection Rate</div>
                <div style='font-size:1rem;font-weight:600;color:{"#22c55e" if rate >= 95 else "#f59e0b" if rate >= 85 else "#ef4444"};margin-top:2px;'>{rate:.1f}%</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Weeks Tracked</div>
                <div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{total_weeks} <span style='color:#f59e0b;font-size:.85rem;'>({fu_weeks} follow-up)</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── Weekly billed vs paid chart ─────────────────────────────────────────────
client_recon = queries.client_weekly_recon_with_dos(conn, selected)

if not client_recon.empty:
    st.markdown(
        "<div class='section-header'><h3>📊 Weekly Billed vs Paid</h3></div>",
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        client_billed_paid_chart(client_recon),
        width="stretch",
        config={"displayModeBar": False},
    )

# ── Full remittance ledger ──────────────────────────────────────────────────
st.markdown(
    "<div class='section-header'><h3>🧾 Payment Ledger</h3></div>",
    unsafe_allow_html=True,
)

# Try with remittance name if we have it
rem_name = selected
if not summary_df.empty and "client_name_remittance" in summary_df.columns:
    alt = summary_df.iloc[0].get("client_name_remittance")
    if alt:
        rem_name = alt

ledger_df = queries.client_ledger(conn, rem_name, sort_asc=True)
if ledger_df.empty:
    ledger_df = queries.client_ledger(conn, selected, sort_asc=True)

if not ledger_df.empty:
    show_unpaid_only = st.checkbox("⏳ Show unpaid/pending line items only (where Paid < Billed)", value=False, key="ledger_show_unpaid")
    if show_unpaid_only:
        ledger_df = ledger_df[ledger_df["paid_hours"] < ledger_df["billed_hours"]]

if ledger_df.empty:
    st.info("No remittance records found for this client.", icon="ℹ️")
else:
    # Calculate deltas for hours and dollars
    ledger_df["hrs_delta"] = ledger_df["billed_hours"] - ledger_df["paid_hours"]
    ledger_df["amt_delta"] = ledger_df["charge_amount"] - ledger_df["payment_amount"]

    display_cols = [c for c in [
        "payment_date", "tcn", "first_dos", "last_dos",
        "transaction_type", "charge_amount", "payment_amount", "amt_delta",
        "billed_hours", "paid_hours", "hrs_delta", "insurance", "match_status",
    ] if c in ledger_df.columns]

    st.dataframe(
        ledger_df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "payment_date":     st.column_config.DateColumn("Payment Date"),
            "tcn":              st.column_config.TextColumn("TCN", width="medium"),
            "first_dos":        st.column_config.DateColumn("First DOS"),
            "last_dos":         st.column_config.DateColumn("Last DOS"),
            "transaction_type": st.column_config.TextColumn("Transaction", width="medium"),
            "charge_amount":    st.column_config.NumberColumn("Billed $", format="$%.2f"),
            "payment_amount":   st.column_config.NumberColumn("Paid $", format="$%.2f"),
            "amt_delta":        st.column_config.NumberColumn("$ Delta", format="$%.2f"),
            "billed_hours":     st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
            "paid_hours":       st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
            "hrs_delta":        st.column_config.NumberColumn("Hrs Delta", format="%.1f"),
            "insurance":        st.column_config.TextColumn("Insurance", width="small"),
            "match_status":     st.column_config.TextColumn("Status", width="small"),
        },
    )
    st.caption(f"{len(ledger_df):,} remittance records found")

