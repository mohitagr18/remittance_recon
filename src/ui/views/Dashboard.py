"""
src/ui/app.py
Streamlit entry point — COO Executive Dashboard (default landing page).
Run with: streamlit run src/ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd



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
inject_css()

# Suffix cleaning regex pattern
import re
_ROLE_SUFFIX = re.compile(
    r"\s+(?:PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$",
    re.IGNORECASE,
)
def strip_suffix(name: str) -> str:
    return _ROLE_SUFFIX.sub("", name).strip()

# Clear dashboard table selections if redirect flag is set
if st.session_state.get("clear_dashboard_selections"):
    for k in ["top_fu_table_None", "top_fu_table_Skilled", "top_fu_table_Unskilled"]:
        if k in st.session_state:
            st.session_state[k] = {"selection": {"rows": [], "columns": []}}
    st.session_state.clear_dashboard_selections = False

# ── Page header ────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>
            📊 Executive Dashboard
        </h1>
    </div>
    """,
    unsafe_allow_html=True,
)

# Get max year in reconciliation data for default YTD
max_date_res = conn.execute("SELECT max(week_start_date) FROM reconciliation").fetchone()
max_year = 2026  # Fallback default
if max_date_res and max_date_res[0]:
    max_year = pd.to_datetime(max_date_res[0]).year

# ── Top-level filters ─────────────────────────────────────────────────────────
col_p, col_i, col_a, _ = st.columns([1.5, 1.5, 1.0, 3.0])

# Date range selection
import datetime

with col_p:
    date_preset = st.selectbox(
        "📅 Date Period",
        ["Year to Date (YTD)", "Month to Date (MTD)", "Last 4 Weeks", "All Time", "Custom Range"],
        index=3,
        key="dash_date_preset"
    )

with col_i:
    insurance = insurance_filter("dash_ins", in_sidebar=False)

with col_a:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    show_archived = st.checkbox(
        "Show Archived",
        value=False,
        key="dash_show_archived"
    )

start_date = None
end_date = None
today = datetime.date.today()

if date_preset == "Year to Date (YTD)":
    start_date = f"{max_year}-01-01"
elif date_preset == "Month to Date (MTD)":
    start_date = today.replace(day=1).strftime("%Y-%m-%d")
elif date_preset == "Last 4 Weeks":
    start_date = (today - datetime.timedelta(weeks=4)).strftime("%Y-%m-%d")
elif date_preset == "All Time":
    if not show_archived:
        start_date = (today - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
elif date_preset == "Custom Range":
    col_s, col_e = st.columns(2)
    with col_s:
        start_val = st.date_input("Start Date", value=pd.to_datetime(f"{max_year}-01-01").date(), key="dash_start_date")
        start_date = str(start_val)
    with col_e:
        end_val = st.date_input("End Date", value=pd.to_datetime("today").date(), key="dash_end_date")
        end_date = str(end_val)

# ── Render Dashboard Function ─────────────────────────────────────────────
def render_dashboard(care_type_filter: str | None):
    # Determine session keys
    trend_key = f"trend_chart_{care_type_filter}"
    reason_key = f"reason_chart_{care_type_filter}"
    payer_key = f"payer_chart_{care_type_filter}"

    for k in [trend_key, reason_key, payer_key]:
        if f"{k}_rev" not in st.session_state:
            st.session_state[f"{k}_rev"] = 0

    active_trend_key = f"{trend_key}_{st.session_state[f'{trend_key}_rev']}"
    active_reason_key = f"{reason_key}_{st.session_state[f'{reason_key}_rev']}"
    active_payer_key = f"{payer_key}_{st.session_state[f'{payer_key}_rev']}"

    # 1. Parse Payer selection first to rerun and update the global selectbox before loading other data
    if active_payer_key in st.session_state and st.session_state[active_payer_key]:
        sel = st.session_state[active_payer_key]
        if "selection" in sel and "points" in sel["selection"] and sel["selection"]["points"]:
            pt = sel["selection"]["points"][0]
            clicked_payer = pt.get("y")
            if clicked_payer:
                st.session_state["dash_ins"] = clicked_payer
                st.session_state[f"{payer_key}_rev"] += 1
                st.rerun()

    # 2. Parse Trend selection
    selected_week = None
    if active_trend_key in st.session_state and st.session_state[active_trend_key]:
        sel = st.session_state[active_trend_key]
        if "selection" in sel and "points" in sel["selection"] and sel["selection"]["points"]:
            pt = sel["selection"]["points"][0]
            selected_week_str = pt.get("x")
            if selected_week_str:
                try:
                    selected_week = pd.to_datetime(selected_week_str).date()
                except Exception:
                    pass

    # 3. Parse Reason selection
    selected_reason = None
    if active_reason_key in st.session_state and st.session_state[active_reason_key]:
        sel = st.session_state[active_reason_key]
        if "selection" in sel and "points" in sel["selection"] and sel["selection"]["points"]:
            pt = sel["selection"]["points"][0]
            selected_reason = pt.get("y")

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
    payroll_hrs    = float(row.get("total_payroll_hrs", 0) or 0)
    billed_hrs     = float(row.get("total_billed_hrs", 0) or 0)
    paid_hrs       = float(row.get("total_paid_hrs", 0) or 0)
    pending_hrs    = float(row.get("pending_hrs", 0) or 0)
    followup_count = int(row.get("followup_count", 0) or 0)
    rate           = float(row.get("collection_rate_pct", 0) or 0)

    render_kpi_row([
        {"label": "Total Clients",   "value": f"{total_clients:,}",  "sub": "", "color": "blue"},
        {"label": "Payroll Hours",   "value": f"{payroll_hrs:,.0f}", "sub": "", "color": "purple"},
        {"label": "Billed Hours",    "value": f"{billed_hrs:,.0f}",  "sub": "", "color": "blue"},
        {"label": "Paid Hours",      "value": f"{paid_hrs:,.0f}",    "sub": "", "color": "green"},
        {"label": "Pending Hours",   "value": f"{pending_hrs:,.0f}", "sub": "", "color": "yellow"},
        {"label": "Follow-Ups",      "value": str(followup_count),   "sub": "", "color": "red"},
        {"label": "Collection Rate", "value": f"{rate:.0f}%",        "sub": "", "color": "green" if rate >= 95 else "red"},
    ])

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # Render Active selections and Reset button if any chart filter is active
    active_selections = []
    if selected_week:
        import datetime
        we = selected_week + datetime.timedelta(days=6)
        active_selections.append(f"📅 Week: {selected_week.strftime('%b %d')} – {we.strftime('%b %d, %Y')}")
    if selected_reason:
        active_selections.append(f"⚠️ Reason: {selected_reason}")

    if active_selections:
        st.info(
            f"📊 Filtering dashboard by: **{', '.join(active_selections)}**",
            icon="🔍"
        )
        if st.button("Reset Chart Filters", key=f"reset_btn_{care_type_filter}"):
            st.session_state[f"{trend_key}_rev"] += 1
            st.session_state[f"{reason_key}_rev"] += 1
            st.rerun()

    # ── Row 1: Rolling trend + Follow-up donut ─────────────────────────────────
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        st.markdown(
            "<div class='section-header'><h3>📈 12-Week Recon Trend</h3></div>",
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
        st.plotly_chart(
            rolling_trend_chart(trend_df), 
            use_container_width=True, 
            config={"displayModeBar": False},
            on_select="rerun",
            key=active_trend_key
        )

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
        st.plotly_chart(
            followup_bar_chart(reason_df), 
            use_container_width=True, 
            config={"displayModeBar": False},
            on_select="rerun",
            key=active_reason_key
        )

    # ── Row 2: Top Follow-Up Clients (deduplicated) ────────────────────────────
    st.markdown(
        "<div class='section-header'><h3>⚠️ Top Follow-Up Clients</h3></div>",
        unsafe_allow_html=True,
    )

    top_fu = queries.top_followup_clients(
        conn, 
        insurance=insurance, 
        limit=50, 
        care_type=care_type_filter,
        start_date=start_date,
        end_date=end_date,
        week_start=str(selected_week) if selected_week else None
    )

    if selected_reason:
        if not top_fu.empty:
            top_fu = top_fu[top_fu["reason"] == selected_reason]

    if top_fu.empty:
        st.success("✅ No follow-ups for the selected filters!", icon="✅")
    else:
        display = top_fu.copy()
        show_cols = ["insurance", "client",
                     "payroll_hours", "billed_hours", "paid_hours",
                     "pending_hrs", "reason"]
        show_cols = [c for c in show_cols if c in display.columns]

        st.caption(f"Showing top {len(display)} follow-up clients · 1 row per client · sorted by pending hrs ↓ · click client to view details")
        selection = st.dataframe(
            display[show_cols],
            use_container_width=True,
            hide_index=True,
            height=min(60 + len(display) * 35, 400),
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "insurance":         st.column_config.TextColumn("Insurance",     width="small"),
                "client":            st.column_config.TextColumn("Client",        width="medium"),
                "payroll_hours":     st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
                "billed_hours":      st.column_config.NumberColumn("Billed Hrs",  format="%.1f"),
                "paid_hours":        st.column_config.NumberColumn("Paid Hrs",    format="%.1f"),
                "pending_hrs":       st.column_config.NumberColumn("⏳ Pending Hrs", format="%.1f"),
                "reason":            st.column_config.TextColumn("Reason",        width="medium"),
            },
            key=f"top_fu_table_{care_type_filter}"
        )

        selected_rows = selection.selection.rows if selection.selection else []
        if selected_rows:
            row_data = display.iloc[selected_rows[0]]
            selected_client = row_data["client"]
            st.session_state.selected_client_ledger = strip_suffix(selected_client)

            # Set care type from row's care_type if present, otherwise fallback to filter
            row_care_type = row_data.get("care_type")
            st.session_state.selected_care_type = row_care_type or care_type_filter

            st.session_state.clear_dashboard_selections = True
            st.switch_page("views/1_Client_Ledger.py")

    # ── Row 3: Recent Payments & Denials (Side-by-Side) ──────────────────────────
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    col_payments, col_denials = st.columns(2, gap="large")

    temp_start_date = start_date
    temp_end_date = end_date
    if selected_week:
        import datetime
        temp_start_date = str(selected_week)
        temp_end_date = str(selected_week + datetime.timedelta(days=6))

    with col_payments:
        st.markdown(
            "<div class='section-header'><h3>💰 Recent Payments</h3></div>",
            unsafe_allow_html=True,
        )
        pay_df = queries.recent_payments(
            conn,
            start_date=temp_start_date,
            end_date=temp_end_date,
            insurance=insurance,
            care_type=care_type_filter,
            limit=10
        )
        if pay_df.empty:
            st.info("No recent payments found.", icon="ℹ️")
        else:
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
            start_date=temp_start_date,
            end_date=temp_end_date,
            insurance=insurance,
            care_type=care_type_filter,
            limit=10
        )
        if den_df.empty:
            st.success("✅ No recent denials or short-pays!", icon="✅")
        else:
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
    st.plotly_chart(
        payer_bar_chart(payer_df), 
        use_container_width=True, 
        config={"displayModeBar": False},
        on_select="rerun",
        key=active_payer_key
    )


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

