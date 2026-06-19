"""
src/ui/views/7_Copay_Manager.py
Copay Management & Reconciliation page.

Two tabs:
  1. Copay Status  — insurance-first view, clicking a row navigates to
                     the Client Ledger pre-filtered to that client/month
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

# Copay tolerance: at least $1 OR 5% of copay amount.
COPAY_TOL_FIXED = 1.00
COPAY_TOL_PCT   = 0.05   # 5%


def _copay_tol(copay: float) -> float:
    """Dynamic tolerance: max($1, 5% of copay amount)."""
    return max(COPAY_TOL_FIXED, copay * COPAY_TOL_PCT)


STATUS_CONFIG = {
    "Client Owes Copay":         {"icon": "💳", "color": "#a78bfa", "bg": "#1e1535",
                                  "action": "Copay due from client."},
    "All Paid – No Action":      {"icon": "✅", "color": "#22c55e", "bg": "#0d2318",
                                  "action": "No outstanding balance."},
    "Insurance Underpaid":       {"icon": "⚠️",  "color": "#f59e0b", "bg": "#1f1a0d",
                                  "action": "Insurance paid less than expected. Follow up with payer."},
    "Copay Partially Collected": {"icon": "🔶", "color": "#f97316", "bg": "#1f1208",
                                  "action": "Client paid only part of the copay."},
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

_NON_INSURANCE_STATUSES = {"Client Owes Copay", "Copay Partially Collected", "All Paid – No Action"}
_INSURANCE_STATUSES     = {"Insurance Underpaid", "Unusual – Needs Review"}


def _status(pending: float, copay: float) -> str:
    tol = _copay_tol(copay)
    if abs(pending) <= COPAY_TOL_FIXED:
        internal = "Fully Paid"
    elif abs(pending - copay) <= tol:
        internal = "Copay Paid"
    elif pending > copay + tol:
        internal = "Exceeds Copay"
    elif 0 < pending < copay - tol:
        internal = "Partial Copay"
    else:
        internal = "Follow Up"
    return _INTERNAL_TO_DISPLAY[internal]


def _insurance_shortfall(status: str, pending: float, copay: float) -> float:
    """Net amount the insurer owes (positive = underpaid, negative = overpaid)."""
    if status == "Insurance Underpaid":
        # Insurer owes: pending minus the copay the client is responsible for
        return round(pending - copay, 2)
    if status == "Unusual – Needs Review":
        # Unexpected balance — could be negative (overpayment)
        return round(pending, 2)
    return 0.0


def _action_text(status: str, pending: float, copay: float) -> str:
    if status == "Insurance Underpaid":
        return f"Follow up with payer — owes ${pending - copay:,.2f}."
    if status == "Unusual – Needs Review":
        return f"Review remittance — unexpected balance of ${pending:,.2f}."
    if status == "Client Owes Copay":
        return f"Copay month logged (${copay:,.2f})."
    if status == "Copay Partially Collected":
        return f"Partial copay month logged (${pending:,.2f} open)."
    if status == "All Paid – No Action":
        return "No outstanding balance."
    return ""


def _get_care_type(conn, client_name: str) -> str:
    """Return 'Skilled' or 'Unskilled' for the given client, defaulting to 'Skilled'."""
    try:
        row = conn.execute("""
            SELECT care_type
            FROM reconciliation
            WHERE UPPER(client_name_payroll) = UPPER(?)
            GROUP BY care_type
            ORDER BY COUNT(*) DESC
            LIMIT 1
        """, [client_name]).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return "Skilled"


def _build_display_df(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        status  = _status(r["pending_dollars"], r["copay_amount"])
        cfg_s   = STATUS_CONFIG.get(status, {})
        copay   = float(r["copay_amount"])
        billed  = float(r["total_billed_dollars"])
        paid    = float(r["total_paid_dollars"])
        # "Insurance Paid" = what insurer actually paid (excl. copay responsibility)
        # "Total Paid"     = insurance paid + copay (what we'd ideally collect in full)
        rows.append({
            "Client":              r["client_name"],
            "Insurance":           r.get("insurance", "—") or "—",
            "Month":               r["month_label"],
            "yr":                  int(r["yr"]),
            "mo":                  int(r["mo"]),
            "Status":              f"{cfg_s.get('icon', '')} {status}",
            "Action":              _action_text(status, r["pending_dollars"], copay),
            "Insurance Shortfall": _insurance_shortfall(status, r["pending_dollars"], copay),
            "Billed":              billed,
            "Ins. Paid":           paid,
            "Copay":               copay,
            "Total Paid":          round(paid + copay, 2),
            "Pending":             r["pending_dollars"],
            "_status_key":         status,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            ["Insurance Shortfall", "Insurance", "Client", "Month"],
            ascending=[False, True, True, True],
        )
    return out


def _build_payer_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Payer", "Clients Affected", "Open Months",
                                     "Total Insurance Shortfall", "Oldest Open Month"])
    tmp = _build_display_df(df)
    grp = tmp.groupby("Insurance", dropna=False).agg(
        clients_affected=("Client", "nunique"),
        open_months=("Month", "count"),
        total_shortfall=("Insurance Shortfall", "sum"),
    ).reset_index()
    oldest = df.copy()
    oldest["insurance"] = oldest["insurance"].fillna("—").astype(str)
    oldest["_sort"] = oldest["yr"] * 100 + oldest["mo"]
    oldest = oldest.sort_values("_sort").groupby("insurance", dropna=False).first().reset_index()
    oldest = oldest[["insurance", "month_label"]].rename(
        columns={"insurance": "Insurance", "month_label": "Oldest Open Month"}
    )
    grp = grp.merge(oldest, on="Insurance", how="left")
    grp = grp.rename(columns={
        "Insurance": "Payer",
        "clients_affected": "Clients Affected",
        "open_months": "Open Months",
        "total_shortfall": "Total Insurance Shortfall",
    }).sort_values("Total Insurance Shortfall", ascending=False)
    return grp


st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>📋 Copay Manager</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Monthly copay reconciliation — prioritize insurance shortfalls first.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2 = st.tabs(["📊 Copay Status", "⚙️ Manage Copays"])


with tab1:
    conn = _conn()
    df_all = queries.copay_monthly_status(conn)

    if df_all.empty:
        st.info("No copay data found. Ensure copay_clients has amounts and reconciliation data exists.")
    else:
        df_all["status"] = df_all.apply(
            lambda r: _status(r["pending_dollars"], r["copay_amount"]), axis=1
        )

        month_opts = sorted(
            df_all[["yr", "mo", "month_label"]].drop_duplicates().values.tolist(),
            key=lambda x: (x[0], x[1]),
        )
        month_labels = [m[2] for m in month_opts]
        current_label = date.today().strftime("%b %Y")
        default_month = current_label if current_label in month_labels else month_labels[-1]

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

        df = df_all.copy() if show_all else df_all[df_all["month_label"] == sel_month].copy()

        insurance_df     = df[df["status"].isin(_INSURANCE_STATUSES)].copy()
        non_insurance_df = df[df["status"].isin(_NON_INSURANCE_STATUSES)].copy()
        total_shortfall  = float(sum(
            _insurance_shortfall(r["status"], r["pending_dollars"], r["copay_amount"])
            for _, r in insurance_df.iterrows()
        ))
        affected_clients = int(insurance_df["client_name"].nunique()) if not insurance_df.empty else 0

        scope_label = "All Months" if show_all else sel_month
        k1, k2, k3 = st.columns(3)
        k1.metric(f"📅 {scope_label}", f"{affected_clients} clients with insurance issues")
        k2.metric("🏢 Payers Owing",
                  f"{insurance_df['insurance'].fillna('—').nunique() if not insurance_df.empty else 0}")
        k3.metric("⚠️ Insurance Shortfall", f"${total_shortfall:,.2f}",
                  help="Amount to follow up with insurers, net of assumed copay.")

        st.markdown("---")

        if not insurance_df.empty:
            payer_summary = _build_payer_summary(insurance_df)
            st.markdown("#### 🏢 Payer Summary")
            st.dataframe(
                payer_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Payer":                     st.column_config.TextColumn("Payer",        width="medium"),
                    "Clients Affected":          st.column_config.NumberColumn("Clients Affected"),
                    "Open Months":               st.column_config.NumberColumn("Open Months"),
                    "Total Insurance Shortfall": st.column_config.NumberColumn("Total Shortfall", format="$%.2f"),
                    "Oldest Open Month":         st.column_config.TextColumn("Oldest Open Month"),
                },
            )

            st.markdown(f"#### ⚠️ Insurance Follow-Up Detail ({len(insurance_df)})")
            st.caption("💡 Click a row to open that client's ledger filtered to the selected month.")

            detail_df = _build_display_df(insurance_df)
            # Column order: Client | Payer | Month | Status | Action | Shortfall | Billed | Ins.Paid | Copay | Total Paid
            display_cols = ["Client", "Insurance", "Month", "Status", "Action",
                            "Insurance Shortfall", "Billed", "Ins. Paid", "Copay", "Total Paid"]

            sel = st.dataframe(
                detail_df[display_cols],
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                column_config={
                    "Client":              st.column_config.TextColumn("Client",    width="medium"),
                    "Insurance":           st.column_config.TextColumn("Payer",     width="medium"),
                    "Month":               st.column_config.TextColumn("Month",     width="small"),
                    "Status":              st.column_config.TextColumn("Status",    width="medium"),
                    "Action":              st.column_config.TextColumn("Action — what to do", width="large"),
                    "Insurance Shortfall": st.column_config.NumberColumn("Shortfall",  format="$%.2f"),
                    "Billed":              st.column_config.NumberColumn("Billed",     format="$%.2f"),
                    "Ins. Paid":           st.column_config.NumberColumn("Ins. Paid",  format="$%.2f"),
                    "Copay":               st.column_config.NumberColumn("Copay",      format="$%.2f"),
                    "Total Paid":          st.column_config.NumberColumn("Total Paid", format="$%.2f",
                                               help="Insurance paid + client copay"),
                },
                key="copay_followup_table",
            )

            selected_rows = sel.selection.rows if sel.selection else []
            if selected_rows:
                chosen      = detail_df.iloc[selected_rows[0]]
                client_name = chosen["Client"]
                yr          = int(chosen["yr"])
                mo          = int(chosen["mo"])
                care_type   = _get_care_type(conn, client_name)

                st.session_state["selected_client_ledger"]    = client_name
                st.session_state["selected_care_type"]        = care_type
                st.session_state["copay_ledger_month_filter"] = (yr, mo)

                if care_type == "Skilled":
                    st.session_state["skilled_selector"]   = client_name
                    st.session_state["unskilled_selector"] = None
                else:
                    st.session_state["unskilled_selector"] = client_name
                    st.session_state["skilled_selector"]   = None

                st.switch_page("views/1_Client_Ledger.py")

        else:
            st.success("✅ No insurance shortfalls for this period.")

        if not non_insurance_df.empty:
            with st.expander(f"📁 Other Copay Months ({len(non_insurance_df)})", expanded=False):
                other = _build_display_df(non_insurance_df).drop(
                    columns=["_status_key", "Insurance Shortfall", "yr", "mo"]
                )
                st.dataframe(
                    other,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Client":     st.column_config.TextColumn("Client",    width="medium"),
                        "Insurance":  st.column_config.TextColumn("Payer",     width="medium"),
                        "Month":      st.column_config.TextColumn("Month",     width="small"),
                        "Status":     st.column_config.TextColumn("Status",    width="medium"),
                        "Action":     st.column_config.TextColumn("Reference", width="large"),
                        "Billed":     st.column_config.NumberColumn("Billed",     format="$%.2f"),
                        "Ins. Paid":  st.column_config.NumberColumn("Ins. Paid",  format="$%.2f"),
                        "Copay":      st.column_config.NumberColumn("Copay",      format="$%.2f"),
                        "Total Paid": st.column_config.NumberColumn("Total Paid", format="$%.2f"),
                        "Pending":    st.column_config.NumberColumn("Pending",    format="$%.2f"),
                    },
                )

        with st.expander("ℹ️ How to read this page", expanded=False):
            st.markdown("- **Insurance Underpaid**: insurer owes money beyond the assumed copay amount.")
            st.markdown("- **Unusual – Needs Review**: balance is unexpected (may be negative = overpayment).")
            st.markdown("- **Ins. Paid**: what the insurer actually remitted.")
            st.markdown("- **Copay**: the fixed monthly copay amount the client owes.")
            st.markdown("- **Total Paid**: Ins. Paid + Copay — what full collection would look like.")
            st.markdown("- **Other Copay Months**: client-copay-oriented rows kept for reference, not primary follow-up.")


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
                max_id = conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM copay_clients"
                ).fetchone()[0]
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
