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
import datetime
import re

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

_copay_month_filter: tuple[int, int] | None = st.session_state.pop(
    "copay_ledger_month_filter", None
)

if "selected_client_ledger" not in st.session_state:
    st.session_state.selected_client_ledger = None
if "selected_care_type" not in st.session_state:
    st.session_state.selected_care_type = None

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
    rate_color  = "#22c55e" if rate >= 95 else "#f59e0b" if rate >= 85 else "#ef4444"

    st.markdown(
        "<div style='background:linear-gradient(135deg,#1e2130,#252840);border:1px solid #2a2d3e;"
        "border-radius:12px;padding:20px 24px;margin-bottom:1.2rem;"
        "display:flex;gap:40px;flex-wrap:wrap;align-items:center;'>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Client</div>"
        f"<div style='font-size:1.1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{selected}</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Insurance</div>"
        f"<div style='font-size:1rem;font-weight:600;color:#4f8ef7;margin-top:2px;'>{ins}</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Payroll Hrs</div>"
        f"<div style='font-size:1rem;font-weight:600;color:#a78bfa;margin-top:2px;'>{ytd_payroll:,.1f}</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Billed Hrs</div>"
        f"<div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{ytd_billed:,.1f}</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Paid Hrs</div>"
        f"<div style='font-size:1rem;font-weight:600;color:#22c55e;margin-top:2px;'>{ytd_paid:,.1f}</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Total Pending Hrs</div>"
        f"<div style='font-size:1rem;font-weight:600;color:#f59e0b;margin-top:2px;'>{ytd_pending:,.1f}</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Collection Rate</div>"
        f"<div style='font-size:1rem;font-weight:600;color:{rate_color};margin-top:2px;'>{rate:.1f}%</div></div>"
        "<div><div style='font-size:0.7rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Weeks Tracked</div>"
        f"<div style='font-size:1rem;font-weight:600;color:#e8eaf0;margin-top:2px;'>{total_weeks} "
        f"<span style='color:#f59e0b;font-size:.85rem;'>({fu_weeks} follow-up)</span></div></div>"
        "</div>",
        unsafe_allow_html=True,
    )

_TILE_STYLE = {
    ("Good",      None):             ("✅",  "#22c55e", "#0d2318", "All Paid \u2013 No Action"),
    ("Good",      "Copay"):          ("💳",  "#a78bfa", "#1e1535", "Copay Month Logged"),
    ("Follow up", "Exceeds Copay"): ("⚠️",  "#f59e0b", "#1f1a0d", "Insurance Underpaid"),
    ("Follow up", "Partial Copay"): ("🔶", "#f97316", "#1f1208", "Partial Copay Month"),
}


def _month_tile(row) -> str:
    key = (row["copay_status"], row.get("copay_note"))
    icon, color, bg, label = _TILE_STYLE.get(
        key, ("\u2753", "#8892a4", "#1e2130", row["copay_status"])
    )
    pending = float(row.get("pending_dollars", 0) or 0)
    billed  = float(row.get("total_billed_dollars", 0) or 0)
    paid    = float(row.get("total_paid_dollars", 0) or 0)
    copay_a = float(row.get("copay_amount", 0) or 0)
    excess  = pending - copay_a if pending > copay_a + 1 else None
    excess_html = (
        '<div style="color:#f59e0b;font-size:0.68rem;margin-top:3px;">'
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
        + excess_html
        + '</div>'
    )


try:
    from src.db.queries import copay_monthly_status, get_copay_table
    _copay_clients_df = get_copay_table(conn)
    _copay_names = (
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
            _copay_amount = float(_client_copay.iloc[0].get("copay_amount", 0) or 0)
            _n_full    = int((_client_copay["copay_note"].isna() & (_client_copay["copay_status"] == "Good")).sum())
            _n_exceeds = int((_client_copay["copay_note"] == "Exceeds Copay").sum())
            _n_partial = int((_client_copay["copay_note"] == "Partial Copay").sum())
            _tiles_html = "".join(_month_tile(row) for _, row in _client_copay.iterrows())
            _insurance_badge = (
                "<span style='background:#1f1a0d;color:#f59e0b;border:1px solid #f59e0b;"
                f"border-radius:5px;padding:2px 8px;font-size:0.75rem;'>{_n_exceeds} \u26a0\ufe0f Insurance Underpaid</span>"
                if _n_exceeds > 0 else ""
            )
            _review_badge = (
                "<span style='background:#1f1208;color:#f97316;border:1px solid #f97316;"
                f"border-radius:5px;padding:2px 8px;font-size:0.75rem;'>{_n_partial} \ud83d\udd36 Partial Copay Months</span>"
                if _n_partial > 0 else ""
            )
            st.markdown(
                "<div style='margin-bottom:1rem;'>"
                "<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;'>"
                "<span style='font-size:1rem;font-weight:700;color:#a78bfa;'>📋 Copay Client</span>"
                f"<span style='font-size:0.82rem;color:#8892a4;'>${_copay_amount:,.2f}/month</span>"
                "<span style='background:#0d2318;color:#22c55e;border:1px solid #22c55e;"
                f"border-radius:5px;padding:2px 8px;font-size:0.75rem;'>\u2705 {_n_full} All Paid</span>"
                + _insurance_badge
                + _review_badge
                + "</div>"
                "<div style='display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;'>"
                + _tiles_html
                + "</div></div>",
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
                "<style>"
                ".element-container:has(div[data-testid='stPlotlyChart']){overflow-x:auto !important;}"
                f"div[data-testid='stPlotlyChart']{{min-width:{num_weeks * 45}px !important;}}"
                "</style>",
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
        f"📊 Filtering to selected week: **{selected_week.strftime('%b %d, %Y')} \u2013 {week_end_date.strftime('%b %d, %Y')}**",
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

_netting_log: list[dict] = []
_netting_by_week: dict   = {}

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
        consolidated_df = consolidated_df.sort_values("first_dos", ascending=True).reset_index(drop=True)

        _payroll = consolidated_df["week_payroll_hours"].fillna(0.0).astype(float)
        _paid    = consolidated_df["paid_hours"].fillna(0.0).astype(float)
        _billed  = consolidated_df["billed_hours"].fillna(0.0).astype(float)
        _delta   = _paid - _payroll

        _adj = [0.0] * len(consolidated_df)

        for i in range(len(consolidated_df) - 1):
            d_cur  = _delta.iloc[i]   + _adj[i]
            d_next = _delta.iloc[i+1] + _adj[i+1]

            if d_cur < -0.9 and d_next > 0.9:
                net = min(abs(d_cur), d_next)
                _adj[i]   += net
                _adj[i+1] -= net
            elif d_cur > 0.9 and d_next < -0.9:
                net = min(d_cur, abs(d_next))
                _adj[i]   -= net
                _adj[i+1] += net

        for i in range(len(consolidated_df)):
            if abs(_adj[i]) < 0.01:
                continue

            idx       = consolidated_df.index[i]
            p_hrs     = float(_payroll.iloc[i])
            pd_eff    = float(_paid.iloc[i]) + _adj[i]
            this_week = consolidated_df.at[idx, "first_dos"]

            # ── Pending hrs: payroll minus effective paid, clamped to 0 ────
            new_pending = max(round(p_hrs - pd_eff, 2), 0.0) if p_hrs > 0 else 0.0
            consolidated_df.at[idx, "week_pending_hrs"] = new_pending

            # ── Status: compare effective paid vs PAYROLL (not billed) ─────
            # Netting is a payroll-vs-paid reconciliation.  Billed may differ
            # (e.g. night-shift hours billed in the adjacent week) and must
            # not drive the post-netting status label.
            if p_hrs > 0:
                if pd_eff > p_hrs + 0.9:
                    base_status = "Paid Extra"
                elif pd_eff >= p_hrs - 0.9:
                    base_status = "Paid in Full"
                else:
                    remain = round(p_hrs - pd_eff, 1)
                    base_status = f"Short Paid ({remain} hrs remain)"
            else:
                b_hrs = float(_billed.iloc[i])
                if pd_eff > b_hrs + 0.9:
                    base_status = "Paid Extra"
                elif pd_eff >= b_hrs - 0.9:
                    base_status = "Paid in Full"
                else:
                    base_status = "Short Paid"

            consolidated_df.at[idx, "reconciled_status"] = base_status + " (adjusted)"

            # ── Neighbor lookup for drill-down note ────────────────────────
            if _adj[i] > 0:
                neighbor_i = i + 1 if i + 1 < len(consolidated_df) else i - 1
            else:
                neighbor_i = i - 1 if i > 0 else i + 1
            neighbor_i    = max(0, min(neighbor_i, len(consolidated_df) - 1))
            neighbor_week = consolidated_df.iloc[neighbor_i]["first_dos"]
            hrs_netted    = round(abs(_adj[i]), 1)

            # per-week drill-down note (shown in daily claims header)
            if _adj[i] > 0:
                _netting_by_week[this_week] = (
                    f"🔀 **{hrs_netted} hrs** short — offset by adjacent week "
                    f"(**{neighbor_week}**) which had a matching excess payment."
                )
            else:
                _netting_by_week[this_week] = (
                    f"🔀 **{hrs_netted} hrs** excess — offset against adjacent week "
                    f"(**{neighbor_week}**) which was short by the same amount."
                )

            # ── Netting log row (simplified — no Direction column) ─────────
            pay_date_str = consolidated_df.at[idx, "payment_date"]
            _netting_log.append({
                "Week":            str(this_week),
                "Adjacent Week":   str(neighbor_week),
                "Hrs Netted":      hrs_netted,
                "Adjusted Status": base_status,
                "Payment Date":    str(pay_date_str) if pay_date_str else "—",
            })

        consolidated_df = consolidated_df.sort_values("first_dos", ascending=False)

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
        "⏳ Show unpaid/pending only (weeks where adjusted pending hrs > 0)",
        value=False, key="ledger_show_unpaid",
    )
    if show_unpaid_only and not consolidated_df.empty:
        consolidated_df = consolidated_df[
            consolidated_df["week_pending_hrs"].fillna(0.0).astype(float) > 0.9
        ]

if ledger_df.empty or consolidated_df.empty:
    st.info("No remittance records found for this client.", icon="ℹ️")
else:
    # ── Netting transparency expander ──────────────────────────────────────
    if _netting_log:
        with st.expander(
            f"🔀 Adjacent-week netting applied to {len(_netting_log)} week(s) — click to see details",
            expanded=False,
        ):
            st.markdown(
                "**❓ What is adjacent-week netting?**"
            )
            st.markdown(
                "When an aide works a night shift that crosses midnight at the Tue→Wed week boundary, "
                "payroll credits the hours to one week while insurance remittance credits the adjacent week. "
                "This creates a misleading alternating Short Paid / Paid Extra pattern that nets to zero economically. "
                "The ledger automatically offsets these weeks so Status and Pending Hrs reflect reality. "
                "Raw remittance data is never modified."
            )
            st.dataframe(
                pd.DataFrame(_netting_log)[["Week", "Adjacent Week", "Hrs Netted", "Adjusted Status", "Payment Date"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Week":            st.column_config.TextColumn("Week (First DOS)"),
                    "Adjacent Week":   st.column_config.TextColumn("Offset Against Week"),
                    "Hrs Netted":      st.column_config.NumberColumn("Hrs Offset", format="%.1f"),
                    "Adjusted Status": st.column_config.TextColumn("Adjusted Status"),
                    "Payment Date":    st.column_config.TextColumn("Payment Date"),
                },
            )

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

        week_claims = daily_claims_df[
            (daily_claims_df["first_dos_date"] >= selected_week_start) &
            (daily_claims_df["first_dos_date"] <= selected_week_end)
        ].copy()

        _drill_netting_note = ""
        if selected_week_start in _netting_by_week:
            _drill_netting_note = (
                "<br><span style='color:#a78bfa;font-size:0.8rem;'>"
                + _netting_by_week[selected_week_start].replace("**", "<b>", 1).replace("**", "</b>", 1)
                  .replace("**", "<b>", 1).replace("**", "</b>", 1)
                + "</span>"
            )

        st.markdown(
            "<div style='margin-top:1.5rem;margin-bottom:0.5rem;'>"
            "<h4 style='margin:0;font-size:1.1rem;font-weight:600;color:#e8eaf0;'>🔍 Daily Claims Detail</h4>"
            "<div style='font-size:0.78rem;color:#8892a4;margin-top:2px;'>"
            f"Showing individual daily remittance records for week <b>{selected_week_start}</b> to <b>{selected_week_end}</b>"
            + _drill_netting_note
            + "</div></div>",
            unsafe_allow_html=True,
        )

        daily_display_cols = [
            "first_dos", "payment_date", "reconciled_status", "week_payroll_hours",
            "billed_hours", "paid_hours", "charge_amount", "payment_amount", "amt_delta", "tcn",
        ]
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
                "billed_hours":       st.column_config.NumberColumn("Billed Hrs",  format="%.1f"),
                "paid_hours":         st.column_config.NumberColumn("Paid Hrs",    format="%.1f"),
                "charge_amount":      st.column_config.NumberColumn("Billed $",    format="$%.2f"),
                "payment_amount":     st.column_config.NumberColumn("Paid $",      format="$%.2f"),
                "amt_delta":          st.column_config.NumberColumn("$ Delta",     format="$%.2f"),
                "tcn":                st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
            },
        )
    else:
        st.info("💡 Click on any week row in the table above to view daily claim details, TCNs, and payment dates.", icon="ℹ️")
