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

import importlib
from src.ui.styles.theme import inject_css
from src.ui.components.kpi_cards import render_kpi_row

from src.ui.components import charts
importlib.reload(charts)
from src.ui.components.charts import rolling_trend_chart, followup_bar_chart, payer_bar_chart, client_billed_paid_chart

from src.ui.components.filters import week_filter, insurance_filter, _get_conn

from src.db import queries
importlib.reload(queries)
conn = _get_conn()


# Get max year in reconciliation data for default YTD
max_date_res = conn.execute("SELECT max(week_start_date) FROM reconciliation").fetchone()
max_year = 2026  # Fallback default
if max_date_res and max_date_res[0]:
    max_year = pd.to_datetime(max_date_res[0]).year

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

# Date range selection
date_preset = st.sidebar.selectbox(
    "📅 Date Period",
    ["Year to Date (YTD)", "All Time", "Custom Range"],
    index=0,
    key="dash_date_preset"
)

start_date = None
end_date = None

if date_preset == "Year to Date (YTD)":
    start_date = f"{max_year}-01-01"
elif date_preset == "Custom Range":
    col_s, col_e = st.sidebar.columns(2)
    with col_s:
        start_val = st.date_input("Start Date", value=pd.to_datetime(f"{max_year}-01-01").date(), key="dash_start_date")
        start_date = str(start_val)
    with col_e:
        end_val = st.date_input("End Date", value=pd.to_datetime("today").date(), key="dash_end_date")
        end_date = str(end_val)

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

# ── Render Dashboard Function ─────────────────────────────────────────────
def render_dashboard(care_type_filter: str | None):
    summary = queries.weekly_summary(
        conn, 
        insurance=insurance, 
        care_type=care_type_filter,
        start_date=start_date,
        end_date=end_date
    )

    if summary.empty or summary.iloc[0]["total_clients"] == 0:
        st.info("⚡ No reconciliation data loaded for the selected filters in this category.", icon="ℹ️")
        return

    row            = summary.iloc[0]
    total_clients  = int(row.get("total_clients", 0) or 0)
    billed_hrs     = float(row.get("total_billed_hrs", 0) or 0)
    paid_hrs       = float(row.get("total_paid_hrs", 0) or 0)
    pending_hrs    = float(row.get("pending_hrs", 0) or 0)
    followup_count = int(row.get("followup_count", 0) or 0)
    rate           = float(row.get("collection_rate_pct", 0) or 0)

    render_kpi_row([
        {"label": "Total Clients",   "value": f"{total_clients:,}",  "sub": "unique active",       "color": "blue"},
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
        trend_df = queries.rolling_trend(
            conn, 
            weeks=12, 
            insurance=insurance, 
            care_type=care_type_filter,
            start_date=start_date,
            end_date=end_date
        )
        st.plotly_chart(rolling_trend_chart(trend_df), width="stretch", config={"displayModeBar": False})

    with col_right:
        st.markdown(
            "<div class='section-header'><h3>🔍 Follow-Up Breakdown</h3></div>",
            unsafe_allow_html=True,
        )
        reason_df = queries.followup_reason_breakdown(
            conn, 
            insurance=insurance, 
            care_type=care_type_filter,
            start_date=start_date,
            end_date=end_date
        )
        st.plotly_chart(followup_bar_chart(reason_df), width="stretch", config={"displayModeBar": False})

    # ── Row 2: Top Follow-Up Clients (deduplicated) ────────────────────────────
    st.markdown(
        "<div class='section-header'><h3>⚠️ Top Follow-Up Clients</h3></div>",
        unsafe_allow_html=True,
    )

    top_fu = queries.top_followup_clients(
        conn, 
        insurance=insurance, 
        limit=15, 
        care_type=care_type_filter,
        start_date=start_date,
        end_date=end_date
    )

    if top_fu.empty:
        st.success("✅ No follow-ups for the selected filters!", icon="✅")
    else:
        display = top_fu.copy()
        show_cols = ["insurance", "client",
                     "payroll_hours", "billed_hours", "paid_hours",
                     "pending_hrs", "payroll_vs_billed", "reason"]
        show_cols = [c for c in show_cols if c in display.columns]

        st.caption(f"Showing top {len(display)} follow-up clients · 1 row per client · sorted by pending hrs ↓ · click client to view details")
        selection = st.dataframe(
            display[show_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "insurance":         st.column_config.TextColumn("Insurance",     width="small"),
                "client":            st.column_config.TextColumn("Client",        width="medium"),
                "payroll_hours":     st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
                "billed_hours":      st.column_config.NumberColumn("Billed Hrs",  format="%.1f"),
                "paid_hours":        st.column_config.NumberColumn("Paid Hrs",    format="%.1f"),
                "pending_hrs":       st.column_config.NumberColumn("⏳ Pending Hrs", format="%.1f"),
                "payroll_vs_billed": st.column_config.NumberColumn("PvB Δ",       format="%.1f"),
                "reason":            st.column_config.TextColumn("Reason",        width="medium"),
            },
            key=f"top_fu_table_{care_type_filter}"
        )

        selected_rows = selection.selection.rows if selection.selection else []
        if selected_rows:
            selected_client = display.iloc[selected_rows[0]]["client"]
            st.session_state.selected_client_from_dashboard = selected_client
            st.rerun()

    # ── Row 3: Recent Payments & Denials (Side-by-Side) ──────────────────────────
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    col_payments, col_denials = st.columns(2, gap="large")

    with col_payments:
        st.markdown(
            "<div class='section-header'><h3>💰 Recent Payments</h3></div>",
            unsafe_allow_html=True,
        )
        pay_df = queries.recent_payments(
            conn,
            start_date=start_date,
            end_date=end_date,
            insurance=insurance,
            care_type=care_type_filter,
            limit=10
        )
        if pay_df.empty:
            st.info("No recent payments found.", icon="ℹ️")
        else:
            # Arrange columns in order: Client Name, Payment Date, First DOS, Billed Hrs, Paid Hrs, Billed $, Paid $
            pay_display_cols = ["client", "payment_date", "first_dos", "billed_hrs", "paid_hrs", "billed_amt", "paid_amt"]
            pay_df = pay_df[pay_display_cols]
            st.dataframe(
                pay_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "client":       st.column_config.TextColumn("Client Name", width="medium"),
                    "payment_date": st.column_config.DateColumn("Payment Date"),
                    "first_dos":    st.column_config.DateColumn("First DOS"),
                    "billed_hrs":   st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
                    "paid_hrs":     st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
                    "billed_amt":   st.column_config.NumberColumn("Billed $", format="$%.2f"),
                    "paid_amt":     st.column_config.NumberColumn("Paid $", format="$%.2f"),
                }
            )

    with col_denials:
        st.markdown(
            "<div class='section-header'><h3>⚠️ Recent Denials / Short-Pays</h3></div>",
            unsafe_allow_html=True,
        )
        den_df = queries.recent_denials(
            conn,
            start_date=start_date,
            end_date=end_date,
            insurance=insurance,
            care_type=care_type_filter,
            limit=10
        )
        if den_df.empty:
            st.success("✅ No recent denials or short-pays!", icon="✅")
        else:
            # Arrange columns in order: Client Name, Denial Date, First DOS, Billed Hrs, Paid Hrs, Pending Hrs, Billed $, Paid $, $ Delta
            den_display_cols = ["client", "payment_date", "first_dos", "billed_hrs", "paid_hrs", "pending_hrs", "billed_amt", "paid_amt", "amt_delta"]
            den_df = den_df[den_display_cols]
            st.dataframe(
                den_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "client":       st.column_config.TextColumn("Client Name", width="medium"),
                    "payment_date": st.column_config.DateColumn("Denial Date"),
                    "first_dos":    st.column_config.DateColumn("First DOS"),
                    "billed_hrs":   st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
                    "paid_hrs":     st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
                    "pending_hrs":  st.column_config.NumberColumn("Pending Hrs", format="%.1f"),
                    "billed_amt":   st.column_config.NumberColumn("Billed $", format="$%.2f"),
                    "paid_amt":     st.column_config.NumberColumn("Paid $", format="$%.2f"),
                    "amt_delta":    st.column_config.NumberColumn("$ Delta", format="$%.2f"),
                }
            )

    # ── Row 4: Payer Collection Rates ──────────────────────────────────────────
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='section-header'><h3>🏥 Payer Collection Rates</h3></div>",
        unsafe_allow_html=True,
    )
    payer_df = queries.payer_collection_rates(
        conn, 
        care_type=care_type_filter,
        start_date=start_date,
        end_date=end_date
    )
    st.plotly_chart(payer_bar_chart(payer_df), width="stretch", config={"displayModeBar": False})


# ── Render Client Detail View or Tabs ──────────────────────────────────────
selected_client = st.session_state.get("selected_client_from_dashboard")

if selected_client:
    # Client header view
    st.markdown(
        f"""
        <div style='margin-bottom:1.2rem; display: flex; align-items: center; gap: 16px;'>
            <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>
                📒 Client detail: {selected_client}
            </h1>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Executive Dashboard", key="btn_back_to_dash"):
        st.session_state.selected_client_from_dashboard = None
        # Reset selection states
        for k in ["top_fu_table_None", "top_fu_table_Skilled", "top_fu_table_Unskilled"]:
            if k in st.session_state:
                st.session_state[k] = {"selection": {"rows": [], "columns": []}}
        st.rerun()

    # ── Summary card ────────────────────────────────────────────────────────────
    summary_df = queries.client_summary(conn, selected_client)

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
                    <div style='font-size:1.1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{selected_client}</div>
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
    client_recon = queries.client_weekly_recon_with_dos(
        conn, selected_client, start_date=start_date, end_date=end_date
    )

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

    rem_name = selected_client
    if not summary_df.empty and "client_name_remittance" in summary_df.columns:
        alt = summary_df.iloc[0].get("client_name_remittance")
        if alt:
            rem_name = alt

    ledger_df = queries.client_ledger(conn, rem_name, start_date=start_date, end_date=end_date, sort_asc=True)
    if ledger_df.empty:
        ledger_df = queries.client_ledger(conn, selected_client, start_date=start_date, end_date=end_date, sort_asc=True)

    if not ledger_df.empty:
        show_unpaid_only = st.checkbox("⏳ Show unpaid/pending line items only (where Paid < Billed)", value=False, key="dash_show_unpaid")
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


else:
    # ── Render tabs ────────────────────────────────────────────────────────────
    tab_overall, tab_skilled, tab_unskilled = st.tabs([
        "🌐 Overall View", 
        "🩺 Skilled Care (PDN)", 
        "🏡 Unskilled Care"
    ])

    with tab_overall:
        render_dashboard(None)

    with tab_skilled:
        render_dashboard("Skilled")

    with tab_unskilled:
        render_dashboard("Unskilled")

