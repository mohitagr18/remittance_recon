"""
src/ui/views/7_Copay_Manager.py
Copay Management & Reconciliation page.

Two tabs:
  1. Copay Status  — current-month first, split into Needs Action / No Action,
                     actionable KPIs with dollar outstanding, action text as headline
  2. Manage Copays — CRUD panel to update amounts and effective dates
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb
from src.ui.styles.theme import inject_css
from src.config import cfg
import importlib
from src.db import queries
importlib.reload(queries)

_DB = cfg.db_path

@st.cache_resource
def _conn():
    return duckdb.connect(str(_DB))

inject_css()

# ── Constants ───────────────────────────────────────────────────────────────
COPAY_TOL = 1.00

STATUS_CONFIG = {
    "Client Owes Copay":         {"icon": "💳", "color": "#a78bfa", "bg": "#1e1535",
                                  "action": "Expected outcome — client owes their monthly copay share."},
    "All Paid – No Action":      {"icon": "✅", "color": "#22c55e", "bg": "#0d2318",
                                  "action": "Insurance covered 100%. Nothing outstanding."},
    "Insurance Underpaid":       {"icon": "⚠️",  "color": "#f59e0b", "bg": "#1f1a0d",
                                  "action": "Insurance paid less than expected. Follow up with payer on the shortfall."},
    "Copay Partially Collected": {"icon": "🔶", "color": "#f97316", "bg": "#1f1208",
                                  "action": "Client has paid part of their copay. Collect the remaining balance."},
    "Unusual – Needs Review":    {"icon": "🔴", "color": "#ef4444", "bg": "#1f0d0d",
                                  "action": "Unexpected balance (e.g. reversal or overpayment). Review remittance records."},
}

_INTERNAL_TO_DISPLAY = {
    "Copay Paid":    "Client Owes Copay",
    "Fully Paid":    "All Paid – No Action",
    "Exceeds Copay": "Insurance Underpaid",
    "Partial Copay": "Copay Partially Collected",
    "Follow Up":     "Unusual – Needs Review",
}

_NO_ACTION_STATUSES       = {"Client Owes Copay", "All Paid – No Action"}
_NEEDS_ATTENTION_STATUSES = {"Insurance Underpaid", "Copay Partially Collected", "Unusual – Needs Review"}


def _status(pending: float, copay: float) -> str:
    if abs(pending) <= COPAY_TOL:
        internal = "Fully Paid"
    elif abs(pending - copay) <= COPAY_TOL:
        internal = "Copay Paid"
    elif pending > copay + COPAY_TOL:
        internal = "Exceeds Copay"
    elif 0 < pending < copay - COPAY_TOL:
        internal = "Partial Copay"
    else:
        internal = "Follow Up"
    return _INTERNAL_TO_DISPLAY[internal]


def _action_text(status: str, pending: float, copay: float) -> str:
    if status == "Client Owes Copay":
        return f"Collect ${copay:,.2f} copay from client."
    if status == "All Paid – No Action":
        return "No outstanding balance."
    if status == "Insurance Underpaid":
        shortfall = pending - copay
        return f"Insurance owes an additional ${shortfall:,.2f} beyond the copay. Follow up with payer."
    if status == "Copay Partially Collected":
        remaining = pending
        return f"${remaining:,.2f} of copay still unpaid. Collect from client."
    if status == "Unusual – Needs Review":
        return f"Balance of ${pending:,.2f} is unexpected. Check for reversals or negative payments."
    return ""


def _badge(label: str) -> str:
    c = STATUS_CONFIG.get(label, {"icon": "❓", "color": "#8892a4", "bg": "#1e2130"})
    return (
        f'<span style="background:{c["bg"]};color:{c["color"]};'
        f'border:1px solid {c["color"]};border-radius:6px;'
        f'padding:2px 10px;font-size:0.8rem;font-weight:600;white-space:nowrap;">'
        f'{c["icon"]} {label}</span>'
    )


def _card_html(row: pd.Series, highlight: bool = False) -> str:
    status = _status(row["pending_dollars"], row["copay_amount"])
    c = STATUS_CONFIG.get(status, {"color": "#8892a4", "bg": "#1e2130"})
    border = f'2px solid {c["color"]}' if highlight else '1px solid #2a2d3e'
    bg     = c["bg"] if highlight else "#1e2130"
    action = _action_text(status, row["pending_dollars"], row["copay_amount"])
    action_color = c["color"] if highlight else "#8892a4"
    return (
        f'<div style="background:{bg};border:{border};border-radius:8px;'
        f'padding:14px 18px;margin-bottom:8px;">'
        # Row 1: action text as headline
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">'
        f'<div style="font-weight:700;color:{action_color};font-size:0.92rem;">{c["icon"]} {action}</div>'
        f'<div>{_badge(status)}</div>'
        f'</div>'
        # Row 2: client + financials as supporting detail
        f'<div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin-top:8px;">'
        f'<div style="min-width:200px;font-weight:600;color:#e8eaf0;font-size:0.88rem;">{row["client_name"]}</div>'
        f'<div style="color:#8892a4;font-size:0.82rem;">{row["month_label"]}</div>'
        f'<div style="color:#c8cfe0;font-size:0.82rem;">Billed: <b>${row["total_billed_dollars"]:,.2f}</b></div>'
        f'<div style="color:#c8cfe0;font-size:0.82rem;">Paid: <b>${row["total_paid_dollars"]:,.2f}</b></div>'
        f'<div style="color:#c8cfe0;font-size:0.82rem;">Pending: <b>${row["pending_dollars"]:,.2f}</b></div>'
        f'<div style="color:#8892a4;font-size:0.78rem;">Copay: ${row["copay_amount"]:,.2f}/mo</div>'
        f'</div>'
        f'</div>'
    )


# ── Page header ────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>📋 Copay Manager</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Monthly copay reconciliation — track what clients and insurers owe each month.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2 = st.tabs(["📊 Copay Status", "⚙️ Manage Copays"])


# ── Tab 1: Copay Status ───────────────────────────────────────────────────────
with tab1:
    conn = _conn()
    df_all = queries.copay_monthly_status(conn)

    if df_all.empty:
        st.info("No copay data found. Ensure copay_clients has amounts and reconciliation data exists.")
    else:
        df_all["status"] = df_all.apply(lambda r: _status(r["pending_dollars"], r["copay_amount"]), axis=1)

        # ─ Derive month options and default to latest ─
        month_opts = sorted(
            df_all[["yr", "mo", "month_label"]].drop_duplicates().values.tolist(),
            key=lambda x: (x[0], x[1]),
        )
        month_labels = [m[2] for m in month_opts]
        default_month = month_labels[-1]  # most recent month

        # ─ Month selector + Show All toggle inline ─
        ctrl_col, toggle_col = st.columns([3, 1])
        with ctrl_col:
            sel_month = st.selectbox(
                "📅 Month",
                options=month_labels,
                index=len(month_labels) - 1,
                label_visibility="collapsed",
                key="copay_month_sel",
            )
        with toggle_col:
            show_all = st.toggle("Show all months", value=False, key="copay_show_all")

        # ─ Apply filters ─
        df = df_all.copy() if show_all else df_all[df_all["month_label"] == sel_month].copy()

        # ─ Actionable KPIs for selected scope ─
        needs_attn = df[df["status"].isin(_NEEDS_ATTENTION_STATUSES)]
        no_action  = df[df["status"].isin(_NO_ACTION_STATUSES)]
        total_outstanding = needs_attn["pending_dollars"].sum()

        scope_label = "All Months" if show_all else sel_month
        k1, k2, k3 = st.columns(3)
        k1.metric(
            f"📅 {scope_label}",
            f"{len(df)} clients tracked",
        )
        k2.metric(
            "✅ No Action Needed",
            f"{len(no_action)}",
            help="Client Owes Copay (expected) or All Paid.",
        )
        k3.metric(
            "⚠️ Needs Action",
            f"{len(needs_attn)}",
            delta=f"${total_outstanding:,.2f} outstanding" if total_outstanding > 0 else None,
            delta_color="inverse",
            help="Insurance Underpaid, Partially Collected, or Unusual balance.",
        )

        st.markdown("---")

        # ─ Client filter (secondary) ─
        client_opts = ["All clients"] + sorted(df["client_name"].unique().tolist())
        sel_client = st.selectbox("Filter by client", client_opts, key="copay_client_sel", label_visibility="collapsed")
        if sel_client != "All clients":
            df = df[df["client_name"] == sel_client]
            needs_attn = df[df["status"].isin(_NEEDS_ATTENTION_STATUSES)]
            no_action  = df[df["status"].isin(_NO_ACTION_STATUSES)]

        # ─ Section 1: Needs Action ─
        if not needs_attn.empty:
            st.markdown(
                f"<div style='font-size:1rem;font-weight:700;color:#f59e0b;margin:12px 0 8px;'>"
                f"⚠️ Needs Action &nbsp;&mdash;&nbsp; {len(needs_attn)} item{'s' if len(needs_attn) != 1 else ''}"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "".join(_card_html(r, highlight=True) for _, r in needs_attn.iterrows()),
                unsafe_allow_html=True,
            )
        else:
            st.success("✅ No action needed for this month.")

        # ─ Section 2: No Action (collapsible) ─
        if not no_action.empty:
            with st.expander(f"✅ No Action Needed ({len(no_action)})", expanded=False):
                st.markdown(
                    "".join(_card_html(r, highlight=False) for _, r in no_action.iterrows()),
                    unsafe_allow_html=True,
                )

        # ─ Legend in collapsible help section ─
        with st.expander("ℹ️ How to read this page", expanded=False):
            for label, c in STATUS_CONFIG.items():
                st.markdown(
                    f'<span style="background:{c["bg"]};color:{c["color"]};border:1px solid {c["color"]};'
                    f'border-radius:6px;padding:2px 10px;font-size:0.8rem;font-weight:600;">'
                    f'{c["icon"]} {label}</span>&nbsp;&nbsp;{c["action"]}',
                    unsafe_allow_html=True,
                )
                st.markdown("")


# ── Tab 2: Manage Copay Amounts & Dates ──────────────────────────────────────────
with tab2:
    st.subheader("Copay Client Management")
    st.caption("Update monthly copay amounts and effective date ranges. Leave dates blank if unknown.")

    conn = _conn()
    clients_df = queries.copay_management(conn)

    for _, row in clients_df.iterrows():
        amt_label = f"${row['copay_amount']:,.2f}/mo" if pd.notna(row['copay_amount']) else "(no amount)"
        with st.expander(f"**{row['client_name']}** — {amt_label}"):
            with st.form(key=f"form_{row['id']}"):
                c1, c2, c3 = st.columns(3)
                new_amt = c1.number_input(
                    "Monthly Copay ($)", min_value=0.0, step=0.01, format="%.2f",
                    value=float(row["copay_amount"]) if pd.notna(row["copay_amount"]) else 0.0,
                )
                eff_from = c2.date_input(
                    "Effective From",
                    value=pd.to_datetime(row["effective_from"]).date() if pd.notna(row["effective_from"]) else None,
                )
                eff_to = c3.date_input(
                    "Effective To",
                    value=pd.to_datetime(row["effective_to"]).date() if pd.notna(row["effective_to"]) else None,
                )
                active = st.checkbox("Active", value=bool(row["is_active"]))
                if st.form_submit_button("💾 Save"):
                    queries.upsert_copay_client(
                        conn,
                        client_id=int(row["id"]),
                        copay_amount=new_amt,
                        effective_from=str(eff_from) if eff_from else None,
                        effective_to=str(eff_to) if eff_to else None,
                        is_active=active,
                    )
                    st.success(f"✅ Saved {row['client_name']} — ${new_amt:,.2f}/mo")
                    st.rerun()

    st.markdown("---")
    st.subheader("➕ Add New Copay Client")
    with st.form("add_new"):
        a1, a2 = st.columns(2)
        new_name  = a1.text_input("Client Name (LAST, FIRST format)")
        new_copay = a2.number_input("Monthly Copay ($)", min_value=0.0, step=0.01, format="%.2f")
        b1, b2    = st.columns(2)
        nf = b1.date_input("Effective From", value=None)
        nt = b2.date_input("Effective To",   value=None)
        if st.form_submit_button("➕ Add Client"):
            if new_name.strip():
                max_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM copay_clients").fetchone()[0]
                conn.execute("""
                    INSERT INTO copay_clients
                        (id, client_name, is_active, copay_amount, effective_from, effective_to, updated_at)
                    VALUES (?, ?, TRUE, ?, CAST(? AS DATE), CAST(? AS DATE), CURRENT_TIMESTAMP)
                """, [max_id + 1, new_name.strip().upper(), new_copay,
                      str(nf) if nf else None, str(nt) if nt else None])
                st.success(f"✅ Added {new_name.strip().upper()} — ${new_copay:,.2f}/mo")
                st.rerun()
            else:
                st.error("Client name is required.")
