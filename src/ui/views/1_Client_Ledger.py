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

# Initialize session state for selected client if not present
if "selected_client_ledger" not in st.session_state:
    st.session_state.selected_client_ledger = None
if "selected_care_type" not in st.session_state:
    st.session_state.selected_care_type = None

# Suffix cleaning regex pattern
import re
_ROLE_SUFFIX = re.compile(
    r"\s+(?:PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$",
    re.IGNORECASE,
)
def strip_suffix(name: str) -> str:
    return _ROLE_SUFFIX.sub("", name).strip()

def on_skilled_change():
    val = st.session_state.skilled_selector
    if val:
        st.session_state.selected_client_ledger = val
        st.session_state.unskilled_selector = None  # Reset unskilled
        st.session_state.selected_care_type = "Skilled"

def on_unskilled_change():
    val = st.session_state.unskilled_selector
    if val:
        st.session_state.selected_client_ledger = val
        st.session_state.skilled_selector = None  # Reset skilled
        st.session_state.selected_care_type = "Unskilled"

# Fetch client lists by care type
try:
    raw_skilled = conn.execute("""
        SELECT DISTINCT client_name_payroll
        FROM reconciliation
        WHERE care_type = 'Skilled' AND client_name_payroll IS NOT NULL
    """).df()["client_name_payroll"].tolist()
    # Case-insensitive dedup: use upper() as the dedup key, keep the canonical
    # form (prefer the version with a role suffix like LPN/RN so we strip it
    # correctly, otherwise just take the first seen).
    def _dedup_names(names):
        seen = {}
        for n in names:
            stripped = strip_suffix(n)
            key = stripped.upper()
            if key not in seen:
                seen[key] = stripped
        return sorted(seen.values())

    skilled_clients = _dedup_names(raw_skilled)

    raw_unskilled = conn.execute("""
        SELECT DISTINCT client_name_payroll
        FROM reconciliation
        WHERE care_type = 'Unskilled' AND client_name_payroll IS NOT NULL
    """).df()["client_name_payroll"].tolist()
    unskilled_clients = _dedup_names(raw_unskilled)
except Exception:
    # Fallback to all if table format differs
    clients = queries.all_clients(conn)
    def _dedup_names(names):
        seen = {}
        for n in names:
            stripped = strip_suffix(n)
            key = stripped.upper()
            if key not in seen:
                seen[key] = stripped
        return sorted(seen.values())
    skilled_clients = _dedup_names(clients)
    unskilled_clients = _dedup_names(clients)

if not skilled_clients and not unskilled_clients:
    st.info("No clients found. Run the ETL pipeline first.", icon="ℹ️")
    st.stop()

# Initialize selectbox state from selected_client_ledger if set
if st.session_state.selected_client_ledger:
    client = st.session_state.selected_client_ledger
    if st.session_state.selected_care_type is None:
        if client in skilled_clients:
            st.session_state.selected_care_type = "Skilled"
        elif client in unskilled_clients:
            st.session_state.selected_care_type = "Unskilled"

    if st.session_state.selected_care_type == "Skilled" and client in skilled_clients:
        st.session_state.skilled_selector = client
        st.session_state.unskilled_selector = None
    elif st.session_state.selected_care_type == "Unskilled" and client in unskilled_clients:
        st.session_state.unskilled_selector = client
        st.session_state.skilled_selector = None

# ── Client selectors ─────────────────────────────────────────────────────────
col_s, col_u, col_a, _ = st.columns([1.5, 1.5, 1.0, 3.0])

with col_s:
    st.selectbox(
        "🩺 Skilled Clients (PDN)",
        options=skilled_clients,
        index=None if st.session_state.get("skilled_selector") is None else (
            skilled_clients.index(st.session_state.skilled_selector) 
            if st.session_state.skilled_selector in skilled_clients else None
        ),
        placeholder="Search skilled client...",
        key="skilled_selector",
        on_change=on_skilled_change,
    )

with col_u:
    st.selectbox(
        "🏡 Unskilled Clients",
        options=unskilled_clients,
        index=None if st.session_state.get("unskilled_selector") is None else (
            unskilled_clients.index(st.session_state.unskilled_selector) 
            if st.session_state.unskilled_selector in unskilled_clients else None
        ),
        placeholder="Search unskilled client...",
        key="unskilled_selector",
        on_change=on_unskilled_change,
    )

with col_a:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    show_archived = st.checkbox("Show Archived", value=False, key="cl_show_archived")

selected = st.session_state.selected_client_ledger

if not selected:
    st.stop()

# ── Summary card ────────────────────────────────────────────────────────────
summary_df = queries.client_summary(conn, selected, care_type=st.session_state.selected_care_type)

if not summary_df.empty:
    row = summary_df.iloc[0]
    ins          = row.get("insurance", "—") or "—"
    ytd_billed   = float(row.get("ytd_billed_hrs", 0) or 0)
    ytd_paid     = float(row.get("ytd_paid_hrs", 0) or 0)
    ytd_payroll  = float(row.get("ytd_payroll_hrs", 0) or 0)
    total_weeks  = int(row.get("total_weeks", 0) or 0)
    fu_weeks     = int(row.get("followup_weeks", 0) or 0)
    rate         = float(row.get("collection_rate_pct", 0) or 0)

    ytd_pending  = float(row.get("ytd_pending_hrs", 0) or 0)

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
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Payroll Hrs</div>
                <div style='font-size:1rem;font-weight:600;color:#a78bfa;margin-top:2px;'>{ytd_payroll:,.1f}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Billed Hrs</div>
                <div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{ytd_billed:,.1f}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Paid Hrs</div>
                <div style='font-size:1rem;font-weight:600;color:#22c55e;margin-top:2px;'>{ytd_paid:,.1f}</div>
            </div>
            <div>
                <div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Pending Hrs</div>
                <div style='font-size:1rem;font-weight:600;color:#f59e0b;margin-top:2px;'>{ytd_pending:,.1f}</div>
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

# ── Weekly billed vs paid chart & pending hours chart ────────────────────────
client_recon = queries.client_weekly_recon_with_dos(conn, selected, care_type=st.session_state.selected_care_type)

if "client_chart_rev" not in st.session_state:
    st.session_state["client_chart_rev"] = 0
active_client_chart_key = f"client_chart_{st.session_state['client_chart_rev']}"

if not client_recon.empty:
    st.markdown(
        "<div class='section-header'><h3>📊 Weekly Reconciliation Trend</h3></div>",
        unsafe_allow_html=True,
    )

    if not show_archived:
        import datetime
        one_year_and_week_ago = (datetime.date.today() - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
        client_recon = client_recon[client_recon["week_start_date"] >= one_year_and_week_ago]

    if not client_recon.empty:
        num_weeks = len(client_recon)
        if num_weeks > 20:
            st.markdown(
                f"""
                <style>
                .element-container:has(div[data-testid="stPlotlyChart"]) {{
                    overflow-x: auto !important;
                }}
                div[data-testid="stPlotlyChart"] {{
                    min-width: {num_weeks * 45}px !important;
                }}
                </style>
                """,
                unsafe_allow_html=True
            )
        selected_points = st.plotly_chart(
            client_billed_paid_chart(client_recon),
            use_container_width=True,
            config={"displayModeBar": False},
            on_select="rerun",
            key=active_client_chart_key,
        )

# Parse chart selection
selected_week = None
if active_client_chart_key in st.session_state and st.session_state[active_client_chart_key]:
    sel = st.session_state[active_client_chart_key]
    if "selection" in sel and "points" in sel["selection"] and sel["selection"]["points"]:
        pt = sel["selection"]["points"][0]
        selected_week_str = pt.get("x") or pt.get("label")
        if selected_week_str:
            try:
                selected_week = pd.to_datetime(selected_week_str).date()
            except Exception:
                pass

# ── Full remittance ledger ──────────────────────────────────────────────────
st.markdown(
    "<div class='section-header'><h3>🧾 Payment Ledger</h3></div>",
    unsafe_allow_html=True,
)

if selected_week:
    import datetime
    week_end_date = selected_week + datetime.timedelta(days=6)
    st.info(
        f"📊 Filtering Payment Ledger by selected week: **{selected_week.strftime('%b %d, %Y')} – {week_end_date.strftime('%b %d, %Y')}**",
        icon="🔍"
    )
    if st.button("Reset Chart Selection", key="btn_reset_client_chart"):
        st.session_state["client_chart_rev"] += 1
        st.rerun()

# Try with remittance name if we have it
rem_name = selected
if not summary_df.empty and "client_name_remittance" in summary_df.columns:
    alt = summary_df.iloc[0].get("client_name_remittance")
    if alt:
        rem_name = alt

ledger_df = queries.client_ledger(conn, rem_name, sort_asc=True, care_type=st.session_state.selected_care_type)
if ledger_df.empty:
    ledger_df = queries.client_ledger(conn, selected, sort_asc=True, care_type=st.session_state.selected_care_type)

if selected_week:
    import datetime
    week_end_date = selected_week + datetime.timedelta(days=6)
    ledger_df["first_dos_date"] = pd.to_datetime(ledger_df["first_dos"]).dt.date
    ledger_df = ledger_df[
        (ledger_df["first_dos_date"] >= selected_week) & 
        (ledger_df["first_dos_date"] <= week_end_date)
    ]

# Apply Archive filter to Payment Ledger
if not show_archived:
    import datetime
    one_year_and_week_ago = (datetime.date.today() - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
    ledger_df = ledger_df[pd.to_datetime(ledger_df["first_dos"]) >= pd.to_datetime(one_year_and_week_ago)]

if not ledger_df.empty:
    # Fill NaNs and do baseline calculations BEFORE filtering
    ledger_df["tcn"] = ledger_df["tcn"].fillna("—")
    ledger_df["billed_hours"] = ledger_df["billed_hours"].fillna(0.0).astype(float)
    ledger_df["paid_hours"] = ledger_df["paid_hours"].fillna(0.0).astype(float)
    ledger_df["charge_amount"] = ledger_df["charge_amount"].fillna(0.0).astype(float)
    ledger_df["payment_amount"] = ledger_df["payment_amount"].fillna(0.0).astype(float)
    ledger_df["amt_delta"] = ledger_df["charge_amount"] - ledger_df["payment_amount"]
    
    ledger_df["week_payroll_hours"] = ledger_df["week_payroll_hours"].fillna(0.0).astype(float)
    ledger_df["week_paid_hours"] = ledger_df["week_paid_hours"].fillna(0.0).astype(float)
    ledger_df["week_pending_hrs"] = (ledger_df["week_payroll_hours"] - ledger_df["week_paid_hours"]).clip(lower=0.0).round(2)

    def compute_rec_status(row):
        tcn_val = row.get("tcn")
        if pd.isna(tcn_val) or tcn_val == "—" or tcn_val is None:
            return "No Remittance Received"
            
        b_hrs = row.get("billed_hours", 0) or 0
        p_hrs = row.get("paid_hours", 0) or 0
        b_amt = row.get("charge_amount", 0) or 0
        p_amt = row.get("payment_amount", 0) or 0
        
        if p_hrs < 0 or p_amt < 0:
            return "Reversal"
        if b_hrs > 0:
            if p_hrs > b_hrs + 0.9:
                return "Paid Extra"
            elif p_hrs >= b_hrs:
                return "Paid in Full"
            elif p_hrs == 0:
                return "Denial / Unpaid"
            else:
                return f"Short Paid ({b_hrs - p_hrs:.1f} hrs remain)"
        if b_amt > 0:
            if p_amt > b_amt + 0.9:
                return "Paid Extra"
            elif p_amt >= b_amt:
                return "Paid in Full"
            elif p_amt == 0:
                return "Denial / Unpaid"
            else:
                return "Short Paid"
        return "Unknown"

    ledger_df["reconciled_status"] = ledger_df.apply(compute_rec_status, axis=1)

    # Map first_dos to Wednesday-start week to group daily claims of the same week together
    import datetime
    def to_week_start(val):
        if pd.isna(val):
            return None
        dt = pd.to_datetime(val).date()
        offset = (dt.weekday() - 2) % 7
        return dt - datetime.timedelta(days=offset)

    ledger_df["week_start"] = ledger_df["first_dos"].apply(to_week_start)
    ledger_df["week_end"] = ledger_df["week_start"].apply(lambda d: d + datetime.timedelta(days=6) if d else None)

    # Save a clean copy of daily claims for drilldown details
    daily_claims_df = ledger_df.copy()

    def get_tcn_display(group):
        tcns = group["tcn"].dropna().unique()
        tcns = [t for t in tcns if t != "—" and t != ""]
        if len(tcns) == 0:
            return "—"
        elif len(tcns) == 1:
            return tcns[0]
        else:
            latest_row = group.loc[group["payment_date"].idxmax()] if group["payment_date"].notna().any() else group.iloc[-1]
            return latest_row.get("tcn") or "Multiple"

    def get_payment_date_display(group):
        dates = group["payment_date"].dropna().dt.date.unique()
        if len(dates) == 0:
            return None
        if len(dates) == 1:
            return dates[0]
        # Multiple payment dates - show all sorted
        sorted_dates = sorted(dates)
        if len(sorted_dates) <= 3:
            return ", ".join(str(d) for d in sorted_dates)
        # If more than 3, show first and last with count
        return f"{sorted_dates[0]} ... {sorted_dates[-1]} ({len(sorted_dates)} payments)"

    def get_status_display(group):
        detailed = group["week_result_detailed"].dropna().unique()
        detailed = [d for d in detailed if d]
        if len(detailed) > 0:
            status = detailed[0]
            if status == "Billed Short":
                return "Billed Short"
            elif status == "Paid Less":
                return "Short Paid"
            elif status == "Not Billed":
                return "Not Billed"
            elif status == "Payer Reversal":
                return "Payer Reversal"
            return status
        # ── Paid Extra override: if paid > payroll after all transactions ──
        p_hrs_chk = float(group["week_payroll_hours"].iloc[0] or 0.0)
        pd_hrs_chk = float(group["week_paid_hours"].iloc[0] or 0.0)
        if p_hrs_chk > 0 and pd_hrs_chk > p_hrs_chk + 0.9:
            return "Paid Extra"
        
        # Fallback to computing from hours:
        p_hrs = float(group["week_payroll_hours"].iloc[0] or 0.0)
        b_hrs = float(group["week_billed_hours"].iloc[0] or 0.0)
        pd_hrs = float(group["week_paid_hours"].iloc[0] or 0.0)
        if p_hrs > 0:
            if b_hrs < p_hrs - 0.9:
                return "Billed Short"
            if pd_hrs > b_hrs + 0.9:
                return "Paid Extra"
            if pd_hrs < b_hrs - 0.9:
                return f"Short Paid ({b_hrs - pd_hrs:.1f} hrs remain)"
            if pd_hrs < p_hrs - 0.9:
                return "Short Paid"
        else:
            if pd_hrs > b_hrs + 0.9:
                return "Paid Extra"
            if pd_hrs < b_hrs - 0.9:
                return "Short Paid"
        if pd_hrs > p_hrs + 0.9:
            return "Paid Extra"
        return "Paid in Full"

    consolidated = []
    for (w_start, w_end), group in ledger_df.groupby(["week_start", "week_end"]):
        w_billed_hrs = group["week_billed_hours"].iloc[0]
        w_paid_hrs = group["week_paid_hours"].iloc[0]
        
        # Find hourly rate from the claims in this group
        rate = None
        for _, r in group.iterrows():
            b_hrs = abs(float(r.get("billed_hours") or 0.0))
            charge = abs(float(r.get("charge_amount") or 0.0))
            if b_hrs > 0.1 and charge > 0.0:
                rate = charge / b_hrs
                break
        if rate is None:
            for _, r in group.iterrows():
                p_hrs = abs(float(r.get("paid_hours") or 0.0))
                pay = abs(float(r.get("payment_amount") or 0.0))
                if p_hrs > 0.1 and pay > 0.0:
                    rate = pay / p_hrs
                    break
        
        sum_payment = group["payment_amount"].sum()
        if abs(w_billed_hrs - w_paid_hrs) <= 0.01:
            charge_amount = sum_payment
        elif rate is not None:
            charge_amount = round(w_billed_hrs * rate, 2)
        else:
            charge_amount = group["charge_amount"].max()
        
        consolidated.append({
            "first_dos": w_start,
            "last_dos": w_end,
            "payment_date": get_payment_date_display(group),
            "reconciled_status": get_status_display(group),
            "week_payroll_hours": group["week_payroll_hours"].iloc[0],
            "billed_hours": w_billed_hrs,
            "paid_hours": w_paid_hrs,
            "week_pending_hrs": group["week_pending_hrs"].iloc[0],
            "charge_amount": charge_amount,
            "payment_amount": sum_payment,
            "amt_delta": max(round(charge_amount - sum_payment, 2), 0.0),
            "tcn": get_tcn_display(group),
        })
    
    consolidated_df = pd.DataFrame(consolidated)
    if not consolidated_df.empty:
        consolidated_df = consolidated_df.sort_values("first_dos", ascending=False)

    show_unpaid_only = st.checkbox("⏳ Show unpaid/pending line items only (where Paid < Billed)", value=False, key="ledger_show_unpaid")
    if show_unpaid_only and not consolidated_df.empty:
        is_payroll_week = consolidated_df["week_payroll_hours"].fillna(0.0).astype(float) > 0.0
        is_unresolved_payroll = (
            is_payroll_week & 
            (consolidated_df["paid_hours"].fillna(0.0).astype(float) < consolidated_df["week_payroll_hours"].fillna(0.0).astype(float) - 0.9)
        )
        is_unresolved_remit = (
            ~is_payroll_week & 
            (consolidated_df["paid_hours"].fillna(0.0).astype(float) < consolidated_df["billed_hours"].fillna(0.0).astype(float) - 0.9)
        )
        consolidated_df = consolidated_df[is_unresolved_payroll | is_unresolved_remit]

if ledger_df.empty or consolidated_df.empty:
    st.info("No remittance records found for this client.", icon="ℹ️")
else:
    st.markdown(
        """
        <div style='font-size:0.82rem;color:#8892a4;margin-bottom:8px;'>
            💡 Select any row in the table below to inspect daily claims and check/TCN numbers.
        </div>
        """,
        unsafe_allow_html=True,
    )

    display_cols = [c for c in [
        "first_dos", "last_dos", "payment_date", "reconciled_status",
        "week_payroll_hours", "billed_hours", "paid_hours", "week_pending_hrs",
        "charge_amount", "payment_amount", "amt_delta", "tcn",
    ] if c in consolidated_df.columns]

    selection = st.dataframe(
        consolidated_df[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=min((len(consolidated_df) + 1) * 35 + 3, 350),
        column_config={
            "first_dos":          st.column_config.DateColumn("First DOS"),
            "last_dos":           st.column_config.DateColumn("Last DOS"),
            "payment_date":       st.column_config.TextColumn("Payment Date"),
            "reconciled_status":  st.column_config.TextColumn("Status", width="medium"),
            "week_payroll_hours": st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
            "billed_hours":       st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
            "paid_hours":         st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
            "week_pending_hrs":   st.column_config.NumberColumn("Pending Hrs", format="%.1f"),
            "charge_amount":      st.column_config.NumberColumn("Billed $", format="$%.2f"),
            "payment_amount":     st.column_config.NumberColumn("Paid $", format="$%.2f"),
            "amt_delta":          st.column_config.NumberColumn("$ Delta", format="$%.2f"),
            "tcn":                st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
        },
        key="consolidated_ledger_table",
    )
    st.caption(f"{len(consolidated_df):,} weeks tracked in ledger")

    # Display drilldown if a week is selected
    selected_rows = selection.selection.rows if selection.selection else []
    if selected_rows:
        selected_idx = selected_rows[0]
        selected_week_start = consolidated_df.iloc[selected_idx]["first_dos"]
        selected_week_end = consolidated_df.iloc[selected_idx]["last_dos"]

        week_claims = daily_claims_df[daily_claims_df["week_start"] == selected_week_start].copy()
        
        st.markdown(
            f"""
            <div style='margin-top:1.5rem;margin-bottom:0.5rem;'>
                <h4 style='margin:0;font-size:1.1rem;font-weight:600;color:#e8eaf0;'>🔍 Daily Claims Detail</h4>
                <div style='font-size:0.78rem;color:#8892a4;margin-top:2px;'>
                    Showing individual daily remittance records for week <b>{selected_week_start}</b> to <b>{selected_week_end}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        daily_display_cols = [
            "first_dos", "payment_date", "reconciled_status",
            "billed_hours", "paid_hours",
            "charge_amount", "payment_amount", "amt_delta", "tcn"
        ]
        
        week_claims = week_claims.sort_values("first_dos")

        st.dataframe(
            week_claims[daily_display_cols],
            use_container_width=True,
            hide_index=True,
            height=min((len(week_claims) + 1) * 35 + 3, 250),
            column_config={
                "first_dos":          st.column_config.DateColumn("Date of Service (DOS)"),
                "payment_date":       st.column_config.DateColumn("Payment Date"),
                "reconciled_status":  st.column_config.TextColumn("Daily Status", width="medium"),
                "billed_hours":       st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
                "paid_hours":         st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
                "charge_amount":      st.column_config.NumberColumn("Billed $", format="$%.2f"),
                "payment_amount":     st.column_config.NumberColumn("Paid $", format="$%.2f"),
                "amt_delta":          st.column_config.NumberColumn("$ Delta", format="$%.2f"),
                "tcn":                st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
            }
        )
    else:
        st.info("💡 Click on any week row in the table above to view daily claim details, TCNs, and payment dates.", icon="ℹ️")


