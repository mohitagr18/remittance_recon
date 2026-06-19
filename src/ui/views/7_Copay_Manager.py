"""
src/ui/views/7_Copay_Manager.py
Copay Management & Reconciliation page.

Two tabs:
  1. Copay Status  — insurance-first view, clicking a row navigates to
                     the Client Ledger pre-filtered to that client/month
  2. Manage Copays — CRUD panel to update amounts and effective dates

Assumption: client copay is always paid in full.
The only question this page answers is: did the insurer pay their expected share?
  Expected insurer share = Billed − Copay
  Shortfall = Expected − Ins. Paid  (positive = underpaid, negative = overpaid)

Row routing:
  Shortfall > tol              → Follow-Up table (counts toward total shortfall metric)
  Shortfall < -tol             → Overpayments FYI expander (excluded from metric)
  |Shortfall| ≤ tol            → Insurance OK expander
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

COPAY_TOL_FIXED = 1.00
COPAY_TOL_PCT   = 0.05


def _copay_tol(copay: float) -> float:
    return max(COPAY_TOL_FIXED, copay * COPAY_TOL_PCT)


STATUS_CONFIG = {
    "Insurance OK":           {"icon": "✅", "color": "#22c55e", "bg": "#0d2318"},
    "Insurance Underpaid":    {"icon": "⚠️",  "color": "#f59e0b", "bg": "#1f1a0d"},
    "Insurer Overpaid":       {"icon": "🔵", "color": "#60a5fa", "bg": "#0d1a2e"},
}

# Only underpaid rows go in the follow-up / metric
_FOLLOW_UP_STATUSES  = {"Insurance Underpaid"}
_OVERPAID_STATUS     = "Insurer Overpaid"
_OK_STATUS           = "Insurance OK"


def _ins_expected(billed: float, copay: float) -> float:
    return round(billed - copay, 2)


def _shortfall(ins_expected: float, ins_paid: float) -> float:
    """Positive = insurer underpaid. Negative = insurer overpaid."""
    return round(ins_expected - ins_paid, 2)


def _status(billed: float, ins_paid: float, copay: float) -> str:
    expected = _ins_expected(billed, copay)
    sf = _shortfall(expected, ins_paid)
    tol = _copay_tol(copay)
    if abs(sf) <= tol:
        return _OK_STATUS
    elif sf > tol:
        return "Insurance Underpaid"
    else:
        return _OVERPAID_STATUS


def _action_text(status: str, shortfall: float) -> str:
    if status == "Insurance Underpaid":
        return f"Follow up with payer — owes ${shortfall:,.2f}."
    if status == _OVERPAID_STATUS:
        return f"Insurer overpaid by ${abs(shortfall):,.2f} — verify remittance."
    return "Insurance paid as expected."


def _get_care_type(conn, client_name: str) -> str:
    try:
        row = conn.execute("""
            SELECT care_type FROM reconciliation
            WHERE UPPER(client_name_payroll) = UPPER(?)
            GROUP BY care_type ORDER BY COUNT(*) DESC LIMIT 1
        """, [client_name]).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return "Skilled"


def _build_display_df(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        billed   = float(r["total_billed_dollars"])
        ins_paid = float(r["total_paid_dollars"])
        copay    = float(r["copay_amount"])
        expected = _ins_expected(billed, copay)
        sf       = _shortfall(expected, ins_paid)
        status   = _status(billed, ins_paid, copay)
        cfg_s    = STATUS_CONFIG.get(status, {})
        rows.append({
            "Client":        r["client_name"],
            "Insurance":     r.get("insurance", "—") or "—",
            "Month":         r["month_label"],
            "yr":            int(r["yr"]),
            "mo":            int(r["mo"]),
            "Status":        f"{cfg_s.get('icon', '')} {status}",
            "Action":        _action_text(status, sf),
            "Shortfall":     sf,
            "Billed":        billed,
            "Ins. Expected": expected,
            "Ins. Paid":     ins_paid,
            "Copay":         copay,
            "_status_key":   status,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            ["Shortfall", "Insurance", "Client", "Month"],
            ascending=[False, True, True, True],
        )
    return out


def _build_payer_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Payer summary for follow-up rows only (positive shortfall)."""
    if df.empty:
        return pd.DataFrame(columns=["Payer", "Clients Affected", "Open Months",
                                     "Total Shortfall", "Oldest Open Month"])
    tmp = _build_display_df(df)
    grp = tmp.groupby("Insurance", dropna=False).agg(
        clients_affected=("Client", "nunique"),
        open_months=("Month", "count"),
        total_shortfall=("Shortfall", "sum"),
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
        "total_shortfall": "Total Shortfall",
    }).sort_values("Total Shortfall", ascending=False)
    return grp


_DETAIL_COL_CONFIG = {
    "Client":        st.column_config.TextColumn("Client",         width="medium"),
    "Insurance":     st.column_config.TextColumn("Payer",          width="medium"),
    "Month":         st.column_config.TextColumn("Month",          width="small"),
    "Status":        st.column_config.TextColumn("Status",         width="medium"),
    "Action":        st.column_config.TextColumn("Action — what to do", width="large"),
    "Billed":        st.column_config.NumberColumn("Billed",        format="$%.2f"),
    "Ins. Expected": st.column_config.NumberColumn("Ins. Expected", format="$%.2f",
                         help="Billed − Copay: what insurer should pay"),
    "Ins. Paid":     st.column_config.NumberColumn("Ins. Paid",     format="$%.2f"),
    "Copay":         st.column_config.NumberColumn("Copay",         format="$%.2f"),
    "Shortfall":     st.column_config.NumberColumn("Shortfall",     format="$%.2f",
                         help="Ins. Expected − Ins. Paid. Positive = insurer owes more."),
}
_DISPLAY_COLS = ["Client", "Insurance", "Month", "Status", "Action",
                 "Billed", "Ins. Expected", "Ins. Paid", "Copay", "Shortfall"]


st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>📋 Copay Manager</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Monthly copay reconciliation — did the insurer pay their expected share?
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
            lambda r: _status(r["total_billed_dollars"], r["total_paid_dollars"], r["copay_amount"]), axis=1
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
                "Month", options=month_labels,
                index=month_labels.index(default_month),
                label_visibility="collapsed", key="copay_month_sel",
            )
        with toggle_col:
            show_all = st.toggle("Show all months", value=False, key="copay_show_all")

        df = df_all.copy() if show_all else df_all[df_all["month_label"] == sel_month].copy()

        followup_df  = df[df["status"].isin(_FOLLOW_UP_STATUSES)].copy()
        overpaid_df  = df[df["status"] == _OVERPAID_STATUS].copy()
        ok_df        = df[df["status"] == _OK_STATUS].copy()

        # Total shortfall: only positive shortfalls (underpaid rows)
        total_shortfall  = float(
            sum(_shortfall(_ins_expected(r["total_billed_dollars"], r["copay_amount"]),
                           r["total_paid_dollars"])
                for _, r in followup_df.iterrows())
        )
        affected_clients = int(followup_df["client_name"].nunique()) if not followup_df.empty else 0

        scope_label = "All Months" if show_all else sel_month
        k1, k2, k3 = st.columns(3)
        k1.metric(f"📅 {scope_label}", f"{affected_clients} clients with insurance issues")
        k2.metric("🏢 Payers Owing",
                  f"{followup_df['insurance'].fillna('—').nunique() if not followup_df.empty else 0}")
        k3.metric("⚠️ Insurance Shortfall", f"${total_shortfall:,.2f}",
                  help="Sum of positive shortfalls only (underpaid rows). Overpayments excluded.")

        st.markdown("---")

        # --- Follow-Up: underpaid only ---
        if not followup_df.empty:
            payer_summary = _build_payer_summary(followup_df)
            st.markdown("#### 🏢 Payer Summary")
            st.dataframe(
                payer_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Payer":             st.column_config.TextColumn("Payer",            width="medium"),
                    "Clients Affected":  st.column_config.NumberColumn("Clients Affected"),
                    "Open Months":       st.column_config.NumberColumn("Open Months"),
                    "Total Shortfall":   st.column_config.NumberColumn("Total Shortfall",  format="$%.2f"),
                    "Oldest Open Month": st.column_config.TextColumn("Oldest Open Month"),
                },
            )

            st.markdown(f"#### ⚠️ Insurance Follow-Up Detail ({len(followup_df)})")
            st.caption("💡 Click a row to open that client's ledger filtered to the selected month.")

            detail_df = _build_display_df(followup_df)
            sel = st.dataframe(
                detail_df[_DISPLAY_COLS],
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                column_config=_DETAIL_COL_CONFIG,
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

        # --- Overpayments: FYI only, collapsed ---
        if not overpaid_df.empty:
            with st.expander(f"🔵 Insurer Overpayments — FYI ({len(overpaid_df)})", expanded=False):
                st.caption("Insurer paid more than expected. No action required, but worth verifying the remittance.")
                op_display = _build_display_df(overpaid_df)
                st.dataframe(
                    op_display[_DISPLAY_COLS],
                    use_container_width=True,
                    hide_index=True,
                    column_config=_DETAIL_COL_CONFIG,
                )

        # --- Insurance OK: collapsed ---
        if not ok_df.empty:
            with st.expander(f"✅ Insurance OK — {len(ok_df)} month(s)", expanded=False):
                ok_display = _build_display_df(ok_df)
                st.dataframe(
                    ok_display[["Client", "Insurance", "Month", "Billed", "Ins. Expected", "Ins. Paid", "Copay", "Shortfall"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config=_DETAIL_COL_CONFIG,
                )

        with st.expander("ℹ️ How to read this page", expanded=False):
            st.markdown("- **Ins. Expected** = Billed − Copay: the share the insurer is responsible for.")
            st.markdown("- **Shortfall** = Ins. Expected − Ins. Paid. Positive = insurer underpaid (follow up).")
            st.markdown("- **Copay** is assumed always paid in full by the client.")
            st.markdown("- **Insurer Overpayments**: insurer paid *more* than expected. Excluded from shortfall total — FYI only.")
            st.markdown("- **Insurance OK**: within tolerance. No action needed.")


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
