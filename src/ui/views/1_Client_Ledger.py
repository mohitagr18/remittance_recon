"""
src/ui/pages/1_Client_Ledger.py
Client Ledger — full payment history per client.
Supports deep-link from Copay Manager via session state:
  st.session_state["copay_ledger_month_filter"] = (yr, mo)
  auto-filters the ledger to weeks falling within that month.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd
import datetime

import importlib
from src.ui.styles.theme import inject_css

from src.ui.components import charts
importlib.reload(charts)
from src.ui.components.charts import client_billed_paid_chart

from src.ui.components.filters import _get_conn

from src.db import queries
importlib.reload(queries)


inject_css()

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

# Consume copay deep-link before anything else — pop so it doesn't persist on refresh
_copay_month_filter: tuple[int, int] | None = st.session_state.pop(
    "copay_ledger_month_filter", None
)

if "selected_client_ledger" not in st.session_state:
    st.session_state.selected_client_ledger = None
if "selected_care_type" not in st.session_state:
    st.session_state.selected_care_type = None

import re
_ROLE_SUFFIX = re.compile(
    r"\s+(?:Live-?[Ii]n|PCA|LPN|RN|CNA|HHA|MA|RN|NP|PA|CHHA|\(LPN\)|\(RN\)|\(PCA\))$",
    re.IGNORECASE,
)
def strip_suffix(name: str) -> str:
    return _ROLE_SUFFIX.sub("", name).strip()

def on_skilled_change():
    val = st.session_state.skilled_selector
    if val:
        st.session_state.selected_client_ledger = val
        st.session_state.unskilled_selector = None
        st.session_state.selected_care_type = "Skilled"

def on_unskilled_change():
    val = st.session_state.unskilled_selector
    if val:
        st.session_state.selected_client_ledger = val
        st.session_state.skilled_selector = None
        st.session_state.selected_care_type = "Unskilled"

try:
    raw_skilled = conn.execute("""
        SELECT DISTINCT client_name_payroll
        FROM reconciliation
        WHERE care_type = 'Skilled' AND client_name_payroll IS NOT NULL
    """).df()["client_name_payroll"].tolist()
    def _dedup_names(names):
        seen = {}
        for n in names:
            stripped = strip_suffix(n)
            key = stripped.upper()
            if key not in seen:
                seen[key] = stripped
        return sorted(seen.values())
    skilled_clients   = _dedup_names(raw_skilled)
    raw_unskilled     = conn.execute("""
        SELECT DISTINCT client_name_payroll
        FROM reconciliation
        WHERE care_type = 'Unskilled' AND client_name_payroll IS NOT NULL
    """).df()["client_name_payroll"].tolist()
    unskilled_clients = _dedup_names(raw_unskilled)
except Exception:
    clients = queries.all_clients(conn)
    def _dedup_names(names):
        seen = {}
        for n in names:
            stripped = strip_suffix(n)
            key = stripped.upper()
            if key not in seen:
                seen[key] = stripped
        return sorted(seen.values())
    skilled_clients   = _dedup_names(clients)
    unskilled_clients = _dedup_names(clients)

if not skilled_clients and not unskilled_clients:
    st.info("No clients found. Run the ETL pipeline first.", icon="ℹ️")
    st.stop()

if st.session_state.selected_client_ledger:
    client = st.session_state.selected_client_ledger
    if st.session_state.selected_care_type is None:
        if client in skilled_clients:
            st.session_state.selected_care_type = "Skilled"
        elif client in unskilled_clients:
            st.session_state.selected_care_type = "Unskilled"
    if st.session_state.selected_care_type == "Skilled" and client in skilled_clients:
        st.session_state.skilled_selector   = client
        st.session_state.unskilled_selector = None
    elif st.session_state.selected_care_type == "Unskilled" and client in unskilled_clients:
        st.session_state.unskilled_selector = client
        st.session_state.skilled_selector   = None

col_s, col_u, col_a, _ = st.columns([1.5, 1.5, 1.0, 3.0])
with col_s:
    st.selectbox(
        "🩺 Skilled Clients (PDN)",
        options=skilled_clients, index=None,
        placeholder="Search skilled client...",
        key="skilled_selector", on_change=on_skilled_change,
    )
with col_u:
    st.selectbox(
        "🏡 Unskilled Clients",
        options=unskilled_clients, index=None,
        placeholder="Search unskilled client...",
        key="unskilled_selector", on_change=on_unskilled_change,
    )
with col_a:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    show_archived = st.checkbox("Show Archived", value=False, key="cl_show_archived")

selected = st.session_state.selected_client_ledger
if not selected:
    st.stop()

# Deep-link banner
if _copay_month_filter:
    _fyr, _fmo = _copay_month_filter
    _month_name = datetime.date(int(_fyr), int(_fmo), 1).strftime("%B %Y")
    st.info(
        f"📋 Navigated from Copay Manager — showing weeks in **{_month_name}** for **{selected}**.",
        icon="🔗",
    )

summary_df = queries.client_summary(conn, selected, care_type=st.session_state.selected_care_type)

if not summary_df.empty:
    row = summary_df.iloc[0]
    ins         = row.get("insurance", "—") or "—"
    ytd_billed  = float(row.get("ytd_billed_hrs", 0) or 0)
    ytd_paid    = float(row.get("ytd_paid_hrs", 0) or 0)
    ytd_payroll = float(row.get("ytd_payroll_hrs", 0) or 0)
    total_weeks = int(row.get("total_weeks", 0) or 0)
    fu_weeks    = int(row.get("followup_weeks", 0) or 0)
    rate        = float(row.get("collection_rate_pct", 0) or 0)
    ytd_pending = float(row.get("ytd_pending_hrs", 0) or 0)

    st.markdown(
        f"""
        <div style='background:linear-gradient(135deg,#1e2130,#252840);border:1px solid #2a2d3e;
                    border-radius:12px;padding:20px 24px;margin-bottom:1.2rem;
                    display:flex;gap:40px;flex-wrap:wrap;align-items:center;'>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Client</div>
                 <div style='font-size:1.1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{selected}</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Insurance</div>
                 <div style='font-size:1rem;font-weight:600;color:#4f8ef7;margin-top:2px;'>{ins}</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Payroll Hrs</div>
                 <div style='font-size:1rem;font-weight:600;color:#a78bfa;margin-top:2px;'>{ytd_payroll:,.1f}</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Billed Hrs</div>
                 <div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{ytd_billed:,.1f}</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Paid Hrs</div>
                 <div style='font-size:1rem;font-weight:600;color:#22c55e;margin-top:2px;'>{ytd_paid:,.1f}</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Pending Hrs</div>
                 <div style='font-size:1rem;font-weight:600;color:#f59e0b;margin-top:2px;'>{ytd_pending:,.1f}</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Collection Rate</div>
                 <div style='font-size:1rem;font-weight:600;color:{"#22c55e" if rate >= 95 else "#f59e0b" if rate >= 85 else "#ef4444"};margin-top:2px;'>{rate:.1f}%</div></div>
            <div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Weeks Tracked</div>
                 <div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{total_weeks} <span style='color:#f59e0b;font-size:.85rem;'>({fu_weeks} follow-up)</span></div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

_TILE_STYLE = {
    ("Good",      None):             ("✅",  "#22c55e", "#0d2318", "All Paid – No Action"),
    ("Good",      "Copay"):          ("💳",  "#a78bfa", "#1e1535", "Copay Month Logged"),
    ("Follow up", "Exceeds Copay"): ("⚠️",  "#f59e0b", "#1f1a0d", "Insurance Underpaid"),
    ("Follow up", "Partial Copay"): ("🔶", "#f97316", "#1f1208", "Partial Copay Month"),
}

try:
    from src.db.queries import copay_monthly_status, get_copay_table
    _copay_clients_df = get_copay_table(conn)
    _copay_names      = (
        set(_copay_clients_df["client_name"].str.upper().tolist())
        if not _copay_clients_df.empty else set()
    )
    _is_copay_client = selected.upper() in _copay_names

    if _is_copay_client:
        _copay_df     = copay_monthly_status(conn)
        _client_copay = _copay_df[
            _copay_df["client_name"].str.upper() == selected.upper()
        ].copy()

        if not _client_copay.empty:
            _client_copay = _client_copay.sort_values(["yr", "mo"])

            def _month_tile(row):
                key      = (row["copay_status"], row.get("copay_note"))
                icon, color, bg, label = _TILE_STYLE.get(
                    key, ("❓", "#8892a4", "#1e2130", row["copay_status"])
                )
                pending  = float(row.get("pending_dollars", 0) or 0)
                billed   = float(row.get("total_billed_dollars", 0) or 0)
                paid     = float(row.get("total_paid_dollars", 0) or 0)
                copay_a  = float(row.get("copay_amount", 0) or 0)
                excess   = pending - copay_a if pending > copay_a + 1 else None
                excess_str = (
                    f'<div style="color:#f59e0b;font-size:0.68rem;margin-top:3px;">'
                    f'+${excess:,.2f} insurance shortfall</div>'
                    if excess else ""
                )
                return (
                    f'<div style="background:{bg};border:1px solid {color};border-radius:10px;'
                    f'padding:12px 14px;min-width:175px;flex:0 0 auto;">'
                    f'<div style="font-size:0.75rem;color:#8892a4;margin-bottom:4px;">{row["month_label"]}</div>'
                    f'<div style="font-size:0.85rem;font-weight:700;color:{color};">{icon} {label}</div>'
                    f'<div style="font-size:0.72rem;color:#c8cfe0;margin-top:6px;">Billed: <b>${billed:,.2f}</b></div>'
                    f'<div style="font-size:0.72rem;color:#c8cfe0;">Paid: <b>${paid:,.2f}</b></div>'
                    f'<div style="font-size:0.72rem;color:{color};font-weight:600;">Pending: ${pending:,.2f}</div>'
                    f'<div style="font-size:0.68rem;color:#8892a4;margin-top:2px;">Copay: ${copay_a:,.2f}/mo</div>'
                    f'{excess_str}</div>'
                )

            _copay_amount = float(_client_copay.iloc[0].get("copay_amount", 0) or 0)
            _n_full       = int((_client_copay["copay_note"].isna() & (_client_copay["copay_status"] == "Good")).sum())
            _n_exceeds    = int((_client_copay["copay_note"] == "Exceeds Copay").sum())
            _n_partial    = int((_client_copay["copay_note"] == "Partial Copay").sum())

            _insurance_badge = (
                f"<span style='background:#1f1a0d;color:#f59e0b;border:1px solid #f59e0b;"
                f"border-radius:5px;padding:2px 8px;font-size:0.75rem;'>{_n_exceeds} ⚠️ Insurance Underpaid</span>"
                if _n_exceeds > 0 else ""
            )
            _review_badge = (
                f"<span style='background:#1f1208;color:#f97316;border:1px solid #f97316;"
                f"border-radius:5px;padding:2px 8px;font-size:0.75rem;'>{_n_partial} 🔶 Partial Copay Months</span>"
                if _n_partial > 0 else ""
            )

            st.markdown(
                f"""
                <div style='margin-bottom:1rem;'>
                    <div style='display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;'>
                        <span style='font-size:1rem;font-weight:700;color:#a78bfa;'>📋 Copay Client</span>
                        <span style='font-size:0.82rem;color:#8892a4;'>${_copay_amount:,.2f}/month</span>
                        <span style='background:#0d2318;color:#22c55e;border:1px solid #22c55e;
                               border-radius:5px;padding:2px 8px;font-size:0.75rem;'>✅ {_n_full} All Paid</span>
                        {_insurance_badge}
                        {_review_badge}
                    </div>
                    <div style='display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;'>
                        {"".join(_month_tile(row) for _, row in _client_copay.iterrows())}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
except Exception:
    pass

client_recon = queries.client_weekly_recon_with_dos(
    conn, selected, care_type=st.session_state.selected_care_type
)

if "client_chart_rev" not in st.session_state:
    st.session_state["client_chart_rev"] = 0
active_client_chart_key = f"client_chart_{st.session_state['client_chart_rev']}"

if not client_recon.empty:
    st.markdown(
        "<div class='section-header'><h3>📊 Weekly Reconciliation Trend</h3></div>",
        unsafe_allow_html=True,
    )
    if not show_archived:
        one_year_ago = (datetime.date.today() - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
        client_recon = client_recon[client_recon["week_start_date"] >= one_year_ago]

    if not client_recon.empty:
        num_weeks = len(client_recon)
        if num_weeks > 20:
            st.markdown(
                f"<style>"
                f".element-container:has(div[data-testid='stPlotlyChart']){{overflow-x:auto !important;}}"
                f"div[data-testid='stPlotlyChart']{{min-width:{num_weeks * 45}px !important;}}"
                f"</style>",
                unsafe_allow_html=True,
            )
        selected_points = st.plotly_chart(
            client_billed_paid_chart(client_recon),
            use_container_width=True,
            config={"displayModeBar": False},
            on_select="rerun",
            key=active_client_chart_key,
        )

selected_week = None
if active_client_chart_key in st.session_state and st.session_state[active_client_chart_key]:
    sel_chart = st.session_state[active_client_chart_key]
    if "selection" in sel_chart and "points" in sel_chart["selection"] and sel_chart["selection"]["points"]:
        pt = sel_chart["selection"]["points"][0]
        selected_week_str = pt.get("x")
        if selected_week_str:
            try:
                selected_week = pd.to_datetime(selected_week_str).date()
            except Exception:
                pass

st.markdown(
    "<div class='section-header'><h3>🧾 Payment Ledger</h3></div>",
    unsafe_allow_html=True,
)

if selected_week:
    week_end_date = selected_week + datetime.timedelta(days=6)
    st.info(
        f"📊 Filtering to selected week: **{selected_week.strftime('%b %d, %Y')} – {week_end_date.strftime('%b %d, %Y')}**",
        icon="🔍",
    )
    if st.button("Reset Chart Selection", key="btn_reset_client_chart"):
        st.session_state["client_chart_rev"] += 1
        st.rerun()

rem_name = selected
if not summary_df.empty and "client_name_remittance" in summary_df.columns:
    alt = summary_df.iloc[0].get("client_name_remittance")
    if alt:
        rem_name = alt

ledger_df = queries.client_ledger(
    conn, rem_name, sort_asc=True, care_type=st.session_state.selected_care_type
)
if ledger_df.empty:
    ledger_df = queries.client_ledger(
        conn, selected, sort_asc=True, care_type=st.session_state.selected_care_type
    )

if selected_week:
    week_end_date = selected_week + datetime.timedelta(days=6)
    ledger_df["first_dos_date"] = pd.to_datetime(ledger_df["first_dos"]).dt.date
    ledger_df = ledger_df[
        (ledger_df["first_dos_date"] >= selected_week) &
        (ledger_df["first_dos_date"] <= week_end_date)
    ]

if not show_archived:
    one_year_ago = (datetime.date.today() - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
    ledger_df = ledger_df[pd.to_datetime(ledger_df["first_dos"]) >= pd.to_datetime(one_year_ago)]

if not ledger_df.empty:
    ledger_df["tcn"]             = ledger_df["tcn"].fillna("—")
    ledger_df["billed_hours"]    = ledger_df["billed_hours"].fillna(0.0).astype(float)
    ledger_df["paid_hours"]      = ledger_df["paid_hours"].fillna(0.0).astype(float)
    ledger_df["charge_amount"]   = ledger_df["charge_amount"].fillna(0.0).astype(float)
    ledger_df["payment_amount"]  = ledger_df["payment_amount"].fillna(0.0).astype(float)
    ledger_df["amt_delta"]       = ledger_df["charge_amount"] - ledger_df["payment_amount"]
    ledger_df["week_payroll_hours"] = ledger_df["week_payroll_hours"].fillna(0.0).astype(float)
    ledger_df["week_paid_hours"]    = ledger_df["week_paid_hours"].fillna(0.0).astype(float)
    ledger_df["week_pending_hrs"]   = (
        ledger_df["week_payroll_hours"] - ledger_df["week_paid_hours"]
    ).clip(lower=0.0).round(2)

    def compute_rec_status(row):
        tcn_val = row.get("tcn")
        if pd.isna(tcn_val) or tcn_val == "—" or tcn_val is None:
            return "No Remittance Received"
        b_hrs = row.get("billed_hours", 0) or 0
        p_hrs = row.get("paid_hours", 0) or 0
        b_amt = row.get("charge_amount", 0) or 0
        p_amt = row.get("payment_amount", 0) or 0
        if p_hrs < 0 or p_amt < 0: return "Reversal"
        if b_hrs > 0:
            if p_hrs > b_hrs + 0.9:  return "Paid Extra"
            elif p_hrs >= b_hrs:     return "Paid in Full"
            elif p_hrs == 0:         return "Denial / Unpaid"
            else:                    return f"Short Paid ({b_hrs - p_hrs:.1f} hrs remain)"
        if b_amt > 0:
            if p_amt > b_amt + 0.9:  return "Paid Extra"
            elif p_amt >= b_amt:     return "Paid in Full"
            elif p_amt == 0:         return "Denial / Unpaid"
            else:                    return "Short Paid"
        return "Unknown"

    ledger_df["reconciled_status"] = ledger_df.apply(compute_rec_status, axis=1)

    def to_week_start(val):
        if pd.isna(val): return None
        dt = pd.to_datetime(val).date()
        return dt - datetime.timedelta(days=(dt.weekday() - 2) % 7)

    ledger_df["week_start"] = ledger_df["first_dos"].apply(to_week_start)
    ledger_df["week_end"]   = ledger_df["week_start"].apply(
        lambda d: d + datetime.timedelta(days=6) if d else None
    )
    ledger_df["first_dos_date"] = pd.to_datetime(ledger_df["first_dos"]).dt.date

    daily_claims_df = ledger_df.copy()

    def get_tcn_display(group):
        tcns = [t for t in group["tcn"].dropna().unique() if t not in ("—", "")]
        if not tcns: return "—"
        if len(tcns) == 1: return tcns[0]
        latest = group.loc[group["payment_date"].idxmax()] if group["payment_date"].notna().any() else group.iloc[-1]
        return latest.get("tcn") or "Multiple"

    def get_payment_date_display(group):
        dates = group["payment_date"].dropna().dt.date.unique()
        if not len(dates): return None
        if len(dates) == 1: return dates[0]
        s = sorted(dates)
        return ", ".join(str(d) for d in s) if len(s) <= 3 else f"{s[0]} ... {s[-1]} ({len(s)} payments)"

    def get_status_display(group):
        detailed = [d for d in group["week_result_detailed"].dropna().unique() if d]
        if detailed:
            s = detailed[0]
            return {"Billed Short": "Billed Short", "Paid Less": "Short Paid",
                    "Not Billed": "Not Billed", "Payer Reversal": "Payer Reversal"}.get(s, s)
        p_hrs  = float(group["week_payroll_hours"].iloc[0] or 0.0)
        pd_hrs = float(group["week_paid_hours"].iloc[0] or 0.0)
        b_hrs  = float(group["week_billed_hours"].iloc[0] or 0.0)
        if p_hrs > 0 and pd_hrs > p_hrs + 0.9: return "Paid Extra"
        if p_hrs > 0:
            if b_hrs < p_hrs - 0.9:             return "Billed Short"
            if pd_hrs > b_hrs + 0.9:            return "Paid Extra"
            if pd_hrs < b_hrs - 0.9:            return f"Short Paid ({b_hrs - pd_hrs:.1f} hrs remain)"
            if pd_hrs < p_hrs - 0.9:            return "Short Paid"
        else:
            if pd_hrs > b_hrs + 0.9:            return "Paid Extra"
            if pd_hrs < b_hrs - 0.9:            return "Short Paid"
        return "Paid in Full"

    consolidated = []
    for (w_start, w_end), group in ledger_df.groupby(["week_start", "week_end"]):
        w_billed_hrs = group["week_billed_hours"].iloc[0]
        w_paid_hrs   = group["week_paid_hours"].iloc[0]
        rate = None
        for _, r in group.iterrows():
            b = abs(float(r.get("billed_hours") or 0.0))
            c = abs(float(r.get("charge_amount") or 0.0))
            if b > 0.1 and c > 0.0: rate = c / b; break
        if rate is None:
            for _, r in group.iterrows():
                p = abs(float(r.get("paid_hours") or 0.0))
                pa = abs(float(r.get("payment_amount") or 0.0))
                if p > 0.1 and pa > 0.0: rate = pa / p; break
        sum_payment   = group["payment_amount"].sum()
        charge_amount = (
            sum_payment if abs(w_billed_hrs - w_paid_hrs) <= 0.01
            else round(w_billed_hrs * rate, 2) if rate is not None
            else group["charge_amount"].max()
        )
        consolidated.append({
            "first_dos":          w_start,
            "last_dos":           w_end,
            "payment_date":       get_payment_date_display(group),
            "reconciled_status":  get_status_display(group),
            "week_payroll_hours": group["week_payroll_hours"].iloc[0],
            "billed_hours":       w_billed_hrs,
            "paid_hours":         w_paid_hrs,
            "week_pending_hrs":   group["week_pending_hrs"].iloc[0],
            "charge_amount":      charge_amount,
            "payment_amount":     sum_payment,
            "amt_delta":          max(round(charge_amount - sum_payment, 2), 0.0),
            "tcn":                get_tcn_display(group),
        })

    consolidated_df = pd.DataFrame(consolidated)
    if not consolidated_df.empty:
        consolidated_df = consolidated_df.sort_values("first_dos", ascending=False)

    # Apply copay month filter from deep-link
    if _copay_month_filter and not consolidated_df.empty:
        _fyr, _fmo = _copay_month_filter
        _month_start = datetime.date(_fyr, _fmo, 1)
        _month_end   = (
            datetime.date(_fyr + 1, 1, 1) - datetime.timedelta(days=1)
            if _fmo == 12
            else datetime.date(_fyr, _fmo + 1, 1) - datetime.timedelta(days=1)
        )
        consolidated_df = consolidated_df[
            (consolidated_df["first_dos"] >= _month_start) &
            (consolidated_df["first_dos"] <= _month_end)
        ]

    show_unpaid_only = st.checkbox(
        "⏳ Show unpaid/pending line items only (where Paid < Payroll)",
        value=False, key="ledger_show_unpaid",
    )
    if show_unpaid_only and not consolidated_df.empty:
        is_pr = consolidated_df["week_payroll_hours"].fillna(0.0).astype(float) > 0.0
        consolidated_df = consolidated_df[
            (is_pr & (consolidated_df["paid_hours"].fillna(0.0).astype(float) <
                      consolidated_df["week_payroll_hours"].fillna(0.0).astype(float) - 0.9)) |
            (~is_pr & (consolidated_df["paid_hours"].fillna(0.0).astype(float) <
                       consolidated_df["billed_hours"].fillna(0.0).astype(float) - 0.9))
        ]

if ledger_df.empty or consolidated_df.empty:
    st.info("No remittance records found for this client.", icon="ℹ️")
else:
    st.markdown(
        "<div style='font-size:0.82rem;color:#8892a4;margin-bottom:8px;'>"
        "💡 Select any row in the table below to inspect daily claims and check/TCN numbers."
        "</div>",
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
            "reconciled_status":  st.column_config.TextColumn("Status",       width="medium"),
            "week_payroll_hours": st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
            "billed_hours":       st.column_config.NumberColumn("Billed Hrs",  format="%.1f"),
            "paid_hours":         st.column_config.NumberColumn("Paid Hrs",    format="%.1f"),
            "week_pending_hrs":   st.column_config.NumberColumn("Pending Hrs", format="%.1f"),
            "charge_amount":      st.column_config.NumberColumn("Billed $",    format="$%.2f"),
            "payment_amount":     st.column_config.NumberColumn("Paid $",      format="$%.2f"),
            "amt_delta":          st.column_config.NumberColumn("$ Delta",     format="$%.2f"),
            "tcn":                st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
        },
        key="consolidated_ledger_table",
    )
    st.caption(f"{len(consolidated_df):,} weeks shown")

    selected_rows = selection.selection.rows if selection.selection else []
    if selected_rows:
        selected_idx        = selected_rows[0]
        selected_week_start = consolidated_df.iloc[selected_idx]["first_dos"]
        selected_week_end   = consolidated_df.iloc[selected_idx]["last_dos"]
        week_payroll        = float(consolidated_df.iloc[selected_idx].get("week_payroll_hours", 0) or 0)

        # Query raw remittance records directly — no aggregation, no is_latest filtering.
        # This shows every individual record exactly as it appears in the master Excel.
        week_claims = queries.client_raw_remittance_claims(
            conn, rem_name, str(selected_week_start), str(selected_week_end)
        )
        if week_claims.empty:
            week_claims = queries.client_raw_remittance_claims(
                conn, selected, str(selected_week_start), str(selected_week_end)
            )

        if not week_claims.empty:
            week_claims["billed_hours"]   = week_claims["billed_hours"].fillna(0.0).astype(float)
            week_claims["paid_hours"]     = week_claims["paid_hours"].fillna(0.0).astype(float)
            week_claims["charge_amount"]  = week_claims["charge_amount"].fillna(0.0).astype(float)
            week_claims["payment_amount"] = week_claims["payment_amount"].fillna(0.0).astype(float)
            week_claims["week_payroll_hours"] = week_payroll
            week_claims["amt_delta"] = (week_claims["charge_amount"] - week_claims["payment_amount"]).clip(lower=0.0).round(2)

            def _claim_status(row):
                p_hrs = float(row.get("paid_hours") or 0)
                b_hrs = float(row.get("billed_hours") or 0)
                p_amt = float(row.get("payment_amount") or 0)
                b_amt = float(row.get("charge_amount") or 0)
                tx    = str(row.get("transaction_type") or "")
                if p_hrs < 0 or p_amt < 0:
                    return "Reversal"
                if b_hrs > 0:
                    if p_hrs >= b_hrs:      return "Paid in Full"
                    elif p_hrs == 0 and p_amt == 0: return "Denial / Unpaid"
                    else:                   return f"Short Paid ({b_hrs - p_hrs:.1f} hrs remain)"
                if b_amt > 0:
                    if p_amt >= b_amt:      return "Paid in Full"
                    elif p_amt == 0:        return "Denial / Unpaid"
                    else:                   return "Short Paid"
                if "Denial" in tx or "Reversal" in tx:
                    return "Denial / Reversal"
                return "Pending"

            week_claims["reconciled_status"] = week_claims.apply(_claim_status, axis=1)

<<<<<<< Updated upstream
=======
        week_claims = daily_claims_df[
            (daily_claims_df["first_dos_date"] >= selected_week_start) &
            (daily_claims_df["first_dos_date"] <= selected_week_end)
        ].copy()

>>>>>>> Stashed changes
        st.markdown(
            f"<div style='margin-top:1.5rem;margin-bottom:0.5rem;'>"
            f"<h4 style='margin:0;font-size:1.1rem;font-weight:600;color:#e8eaf0;'>🔍 Daily Claims Detail</h4>"
            f"<div style='font-size:0.78rem;color:#8892a4;margin-top:2px;'>"
            f"Showing individual daily remittance records for week "
            f"<b>{selected_week_start}</b> to <b>{selected_week_end}</b>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

<<<<<<< Updated upstream
        if week_claims.empty:
            st.info("No remittance records found for this week.", icon="ℹ️")
        else:
            daily_display_cols = [
                "first_dos", "payment_date", "reconciled_status", "week_payroll_hours",
                "billed_hours", "paid_hours", "charge_amount", "payment_amount", "amt_delta", "tcn",
            ]
            daily_display_cols = [c for c in daily_display_cols if c in week_claims.columns]

            st.dataframe(
                week_claims.sort_values("first_dos")[daily_display_cols],
                use_container_width=True,
                hide_index=True,
                height=min((len(week_claims) + 1) * 35 + 3, 250),
                column_config={
                    "first_dos":          st.column_config.DateColumn("Date of Service (DOS)"),
                    "payment_date":       st.column_config.DateColumn("Payment Date"),
                    "reconciled_status":  st.column_config.TextColumn("Daily Status", width="medium"),
                    "week_payroll_hours": st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
                    "billed_hours":       st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
                    "paid_hours":         st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
                    "charge_amount":      st.column_config.NumberColumn("Billed $", format="$%.2f"),
                    "payment_amount":     st.column_config.NumberColumn("Paid $", format="$%.2f"),
                    "amt_delta":          st.column_config.NumberColumn("$ Delta", format="$%.2f"),
                    "tcn":                st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
                },
            )
=======
        daily_display_cols = [
            "first_dos", "payment_date", "reconciled_status", "week_payroll_hours",
            "billed_hours", "paid_hours",
            "charge_amount", "payment_amount", "amt_delta", "tcn"
        ]
        daily_display_cols = [c for c in daily_display_cols if c in week_claims.columns]

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
                "week_payroll_hours": st.column_config.NumberColumn("Payroll Hrs", format="%.1f"),
                "billed_hours":       st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
                "paid_hours":         st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
                "charge_amount":      st.column_config.NumberColumn("Billed $", format="$%.2f"),
                "payment_amount":     st.column_config.NumberColumn("Paid $", format="$%.2f"),
                "amt_delta":          st.column_config.NumberColumn("$ Delta", format="$%.2f"),
                "tcn":                st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
            }
        )
>>>>>>> Stashed changes
    else:
        st.info("💡 Click on any week row in the table above to view daily claim details, TCNs, and payment dates.", icon="ℹ️")
