"""
src/ui/views/7_Copay_Manager.py
Copay Management & Reconciliation page.

Two tabs:
  1. Copay Status  — current-month first, split into Needs Action / No Action tables,
                     actionable KPIs with dollar outstanding
  2. Manage Copays — CRUD panel to update amounts and effective dates
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date
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
                                  "action": "Insurance paid less than expected. Follow up with payer."},
    "Copay Partially Collected": {"icon": "🔶", "color": "#f97316", "bg": "#1f1208",
                                  "action": "Client has paid part of their copay. Collect the remaining balance."},
    "Unusual – Needs Review":    {"icon": "🔴", "color": "#ef4444", "bg": "#1f0d0d",
                                  "action": "Unexpected balance. Review remittance records."},
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
        return f"Follow up with payer — owes ${pending - copay:,.2f} beyond copay."
    if status == "Copay Partially Collected":
        return f"Collect ${pending:,.2f} remaining from client."
    if status == "Unusual – Needs Review":
        return f"Review — unexpected balance of ${pending:,.2f}."
    return ""


def _build_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Convert raw status df into a clean display table."""
    rows = []
    for _, r in df.iterrows():
        status = _status(r["pending_dollars"], r["copay_amount"])
        cfg_s  = STATUS_CONFIG.get(status, {})
        rows.append({
            "Client":       r["client_name"],
            "Month":        r["month_label"],
            "Status":       f"{cfg_s.get('icon', '')} {status}",
            "Action":       _action_text(status, r["pending_dollars"], r["copay_amount"]),
            "Billed":       r["total_billed_dollars"],
            "Paid":         r["total_paid_dollars"],
            "Pending":      r["pending_dollars"],
            "Copay/mo":     r["copay_amount"],
            "_status_key":  status,
        })
    return pd.DataFrame(rows)


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

        # ─ Month options — default to current calendar month, fall back to latest data month ─
        month_opts = sorted(
            df_all[["yr", "mo", "month_label"]].drop_duplicates().values.tolist(),
            key=lambda x: (x[0], x[1]),
        )
        month_labels = [m[2] for m in month_opts]
        current_label = date.today().strftime("%b %Y")  # e.g. "Jun 2026"
        default_month = current_label if current_label in month_labels else month_labels[-1]

        # ─ Month selector + Show All toggle ─
        ctrl_col, toggle_col = st.columns([3, 1])
        with ctrl_col:
            sel_month = st.selectbox(
                "Month",
                options=month_labels,
                index=month_labels.index(default_month),
                label_visibility="collapsed",
                key="copay_month_sel",
            )
        with toggle_col:
            show_all = st.toggle("Show all months", value=False, key="copay_show_all")

        # ─ Filter ─
        df = df_all.copy() if show_all else df_all[df_all["month_label"] == sel_month].copy()

        needs_attn_df = df[df["status"].isin(_NEEDS_ATTENTION_STATUSES)]
        no_action_df  = df[df["status"].isin(_NO_ACTION_STATUSES)]
        total_outstanding = needs_attn_df["pending_dollars"].sum()

        # ─ KPIs ─
        scope_label = "All Months" if show_all else sel_month
        k1, k2, k3 = st.columns(3)
        k1.metric(f"📅 {scope_label}", f"{len(df)} clients tracked")
        k2.metric("✅ No Action Needed", f"{len(no_action_df)}",
                  help="Client Owes Copay (expected) or All Paid.")
        k3.metric("⚠️ Needs Action", f"{len(needs_attn_df)}",
                  delta=f"${total_outstanding:,.2f} outstanding" if total_outstanding > 0 else None,
                  delta_color="inverse",
                  help="Insurance Underpaid, Partially Collected, or Unusual balance.")

        st.markdown("---")

        # ─ Section 1: Needs Action table ─
        if not needs_attn_df.empty:
            st.markdown(f"#### ⚠️ Needs Action &nbsp;({len(needs_attn_df)})")
            disp = _build_display_df(needs_attn_df).drop(columns=["_status_key"])
            st.dataframe(
                disp,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Client":   st.column_config.TextColumn("Client",   width="medium"),
                    "Month":    st.column_config.TextColumn("Month",    width="small"),
                    "Status":   st.column_config.TextColumn("Status",   width="medium"),
                    "Action":   st.column_config.TextColumn("Action — what to do", width="large"),
                    "Billed":   st.column_config.NumberColumn("Billed",   format="$%.2f"),
                    "Paid":     st.column_config.NumberColumn("Paid",     format="$%.2f"),
                    "Pending":  st.column_config.NumberColumn("Pending",  format="$%.2f"),
                    "Copay/mo": st.column_config.NumberColumn("Copay/mo", format="$%.2f"),
                },
            )
        else:
            st.success("✅ No action needed for this period.")

        # ─ Section 2: No Action table (collapsed) ─
        if not no_action_df.empty:
            with st.expander(f"✅ No Action Needed ({len(no_action_df)})", expanded=False):
                disp2 = _build_display_df(no_action_df).drop(columns=["_status_key"])
                st.dataframe(
                    disp2,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Client":   st.column_config.TextColumn("Client",   width="medium"),
                        "Month":    st.column_config.TextColumn("Month",    width="small"),
                        "Status":   st.column_config.TextColumn("Status",   width="medium"),
                        "Action":   st.column_config.TextColumn("Action — what to do", width="large"),
                        "Billed":   st.column_config.NumberColumn("Billed",   format="$%.2f"),
                        "Paid":     st.column_config.NumberColumn("Paid",     format="$%.2f"),
                        "Pending":  st.column_config.NumberColumn("Pending",  format="$%.2f"),
                        "Copay/mo": st.column_config.NumberColumn("Copay/mo", format="$%.2f"),
                    },
                )

        # ─ Legend ─
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
