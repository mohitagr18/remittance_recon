"""
src/ui/views/7_Copay_Manager.py
Copay Management & Monthly Reconciliation page.

Two tabs:
  1. Copay Management  — CRUD table to view/edit all copay clients and amounts
  2. Monthly Copay Status — per-client × month pending vs copay with distinct highlights
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import duckdb
from pathlib import Path

# ── DB connection ──────────────────────────────────────────────────────────────
_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "recon.duckdb"

@st.cache_resource
def _get_conn():
    return duckdb.connect(str(_DB_PATH))

conn = _get_conn()

# ── Helpers ────────────────────────────────────────────────────────────────────

COPAY_COLOR    = "#4fc3f7"   # light blue  — pending = copay (expected)
EXCEED_COLOR   = "#ef5350"   # red         — pending exceeds copay
PARTIAL_COLOR  = "#ffa726"   # amber       — partial copay
PAID_COLOR     = "#66bb6a"   # green       — fully paid

def _status_badge(status: str, note: str | None) -> str:
    if note == "Copay":
        return f'<span style="background:{COPAY_COLOR};color:#000;padding:2px 8px;border-radius:10px;font-size:0.8em;font-weight:600">✦ Copay</span>'
    if note == "Exceeds Copay":
        return f'<span style="background:{EXCEED_COLOR};color:#fff;padding:2px 8px;border-radius:10px;font-size:0.8em;font-weight:600">⚠ Exceeds Copay</span>'
    if note == "Partial Copay":
        return f'<span style="background:{PARTIAL_COLOR};color:#000;padding:2px 8px;border-radius:10px;font-size:0.8em;font-weight:600">⚡ Partial Copay</span>'
    if status == "Good":
        return f'<span style="background:{PAID_COLOR};color:#000;padding:2px 8px;border-radius:10px;font-size:0.8em;font-weight:600">✓ Paid in Full</span>'
    return f'<span style="background:#bdbdbd;color:#000;padding:2px 8px;border-radius:10px;font-size:0.8em;font-weight:600">{status}</span>'

# ── Page layout ────────────────────────────────────────────────────────────────

st.title("💊 Copay Manager")
st.caption("Manage client copay amounts and review monthly copay reconciliation status.")

tab1, tab2 = st.tabs(["📋 Copay Management", "📅 Monthly Copay Status"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — COPAY MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Client Copay Amounts")
    st.caption("Edit copay amounts and effective date ranges. Leave start/end dates blank if unknown.")

    df = conn.execute("""
        SELECT id, client_name, copay_amount, effective_from, effective_to, is_active
        FROM copay_clients ORDER BY client_name
    """).df()

    # Convert date columns for display
    for col in ["effective_from", "effective_to"]:
        df[col] = pd.to_datetime(df[col]).dt.date

    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "client_name": st.column_config.TextColumn("Client Name", width="large"),
            "copay_amount": st.column_config.NumberColumn(
                "Monthly Copay ($)", format="$%.2f", min_value=0.0, step=0.01
            ),
            "effective_from": st.column_config.DateColumn("Copay Start Date", format="MM/DD/YYYY"),
            "effective_to":   st.column_config.DateColumn("Copay End Date",   format="MM/DD/YYYY"),
            "is_active": st.column_config.CheckboxColumn("Active"),
        },
        hide_index=True,
        key="copay_editor",
    )

    if st.button("💾 Save Changes", type="primary"):
        saved = 0
        errors = []
        for _, row in edited.iterrows():
            try:
                eff_from = str(row["effective_from"]) if pd.notna(row["effective_from"]) and row["effective_from"] else None
                eff_to   = str(row["effective_to"])   if pd.notna(row["effective_to"])   and row["effective_to"]   else None
                conn.execute("""
                    UPDATE copay_clients
                    SET copay_amount   = ?,
                        effective_from = CAST(? AS DATE),
                        effective_to   = CAST(? AS DATE),
                        is_active      = ?,
                        updated_at     = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, [float(row["copay_amount"]) if pd.notna(row["copay_amount"]) else None,
                      eff_from, eff_to, bool(row["is_active"]), int(row["id"])])
                saved += 1
            except Exception as e:
                errors.append(f"{row['client_name']}: {e}")
        conn.commit()
        if errors:
            st.error("\n".join(errors))
        else:
            st.success(f"✅ Saved {saved} client records.")
            st.cache_resource.clear()
            st.rerun()

    st.divider()
    st.subheader("➕ Add New Copay Client")
    with st.form("add_copay_client"):
        col1, col2 = st.columns(2)
        new_name   = col1.text_input("Client Name (LAST, FIRST format)")
        new_amount = col2.number_input("Monthly Copay ($)", min_value=0.0, step=0.01, format="%.2f")
        col3, col4 = st.columns(2)
        new_from   = col3.date_input("Copay Start Date", value=None)
        new_to     = col4.date_input("Copay End Date",   value=None)
        submitted  = st.form_submit_button("Add Client")
        if submitted:
            if not new_name.strip():
                st.error("Client name is required.")
            else:
                max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM copay_clients").fetchone()[0]
                conn.execute("""
                    INSERT INTO copay_clients
                        (id, client_name, is_active, copay_amount, effective_from, effective_to, updated_at)
                    VALUES (?, ?, TRUE, ?, CAST(? AS DATE), CAST(? AS DATE), CURRENT_TIMESTAMP)
                """, [max_id + 1, new_name.strip().upper(),
                      float(new_amount),
                      str(new_from) if new_from else None,
                      str(new_to)   if new_to   else None])
                conn.commit()
                st.success(f"✅ Added {new_name.upper()} with copay ${new_amount:.2f}")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MONTHLY COPAY STATUS
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Monthly Copay Reconciliation")
    st.caption(
        "Pending dollars per client per month are compared against their monthly copay. "
        "A **✦ Copay** badge means pending = copay — this is expected and not a problem."
    )

    # Legend
    st.markdown(
        f'''
        <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">
          <div>{_status_badge("Good","Copay")} &nbsp;Pending ≈ monthly copay (expected)</div>
          <div>{_status_badge("Good", None)} &nbsp;Fully paid including copay</div>
          <div>{_status_badge("Follow up","Exceeds Copay")} &nbsp;Pending beyond copay — review</div>
          <div>{_status_badge("Follow up","Partial Copay")} &nbsp;Underpaid relative to copay</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    # Filters
    fcol1, fcol2, fcol3 = st.columns(3)
    all_years  = conn.execute("SELECT DISTINCT DATE_PART('year', week_start_date)::INT AS yr FROM reconciliation ORDER BY yr DESC").df()["yr"].tolist()
    all_months = list(range(1, 13))
    month_names = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}

    sel_year   = fcol1.selectbox("Year",  options=[None] + all_years, format_func=lambda x: "All" if x is None else str(x))
    sel_month  = fcol2.selectbox("Month", options=[None] + all_months, format_func=lambda x: "All" if x is None else month_names[x])
    sel_client = fcol3.selectbox("Client", options=["All"] + sorted(conn.execute("SELECT client_name FROM copay_clients WHERE is_active ORDER BY client_name").df()["client_name"].tolist()))

    # Pull data — using inline SQL since copay_monthly_status query uses dollar estimation
    month_filter = ""
    if sel_year:
        month_filter += f" AND DATE_PART('year', r.week_start_date) = {sel_year}"
    if sel_month:
        month_filter += f" AND DATE_PART('month', r.week_start_date) = {sel_month}"

    status_df = conn.execute(f"""
        WITH copay_active AS (
            SELECT client_name, copay_amount, effective_from, effective_to
            FROM copay_clients
            WHERE is_active = TRUE AND copay_amount IS NOT NULL
        ),
        recon_monthly AS (
            SELECT
                r.client_name_payroll                             AS client_name,
                DATE_PART('year',  r.week_start_date)::INT       AS yr,
                DATE_PART('month', r.week_start_date)::INT       AS mo,
                SUM(r.billed_hours)                               AS billed_hrs,
                SUM(r.paid_hours)                                 AS paid_hrs,
                SUM(GREATEST(COALESCE(r.payroll_hours,0) - COALESCE(r.paid_hours,0), 0)) AS pending_hrs
            FROM reconciliation r
            WHERE r.client_name_payroll IN (SELECT client_name FROM copay_active)
            {month_filter}
            GROUP BY r.client_name_payroll, yr, mo
        ),
        remit_monthly AS (
            SELECT
                UPPER(client_name_combined)   AS client_name_upper,
                DATE_PART('year',  first_dos)::INT  AS yr,
                DATE_PART('month', first_dos)::INT  AS mo,
                SUM(charge_amount)            AS total_billed_dollars,
                SUM(payment_amount)           AS total_paid_dollars
            FROM remittance
            WHERE is_latest = TRUE
            GROUP BY client_name_upper, yr, mo
        ),
        combined AS (
            SELECT
                rm.client_name,
                ca.copay_amount,
                rm.yr,
                rm.mo,
                STRFTIME(MAKE_DATE(rm.yr, rm.mo, 1), '%b %Y') AS month_label,
                ROUND(COALESCE(rem.total_billed_dollars, 0), 2) AS billed_dollars,
                ROUND(COALESCE(rem.total_paid_dollars,   0), 2) AS paid_dollars,
                ROUND(COALESCE(rem.total_billed_dollars, 0) - COALESCE(rem.total_paid_dollars, 0), 2) AS pending_dollars
            FROM recon_monthly rm
            JOIN copay_active ca ON UPPER(ca.client_name) = UPPER(rm.client_name)
            LEFT JOIN remit_monthly rem
              ON UPPER(rem.client_name_upper) LIKE '%' || SPLIT_PART(UPPER(rm.client_name), ',', 1) || '%'
             AND rem.yr = rm.yr AND rem.mo = rm.mo
        )
        SELECT
            client_name,
            copay_amount,
            month_label,
            yr,
            mo,
            billed_dollars,
            paid_dollars,
            pending_dollars,
            CASE
                WHEN ABS(pending_dollars) <= 1.00                        THEN 'Good'
                WHEN ABS(pending_dollars - copay_amount) <= 1.00         THEN 'Good'
                WHEN pending_dollars > copay_amount + 1.00               THEN 'Follow up'
                WHEN pending_dollars > 1.00 AND pending_dollars < copay_amount - 1.00 THEN 'Follow up'
                ELSE 'Good'
            END AS copay_status,
            CASE
                WHEN ABS(pending_dollars) <= 1.00                        THEN NULL
                WHEN ABS(pending_dollars - copay_amount) <= 1.00         THEN 'Copay'
                WHEN pending_dollars > copay_amount + 1.00               THEN 'Exceeds Copay'
                WHEN pending_dollars > 1.00 AND pending_dollars < copay_amount - 1.00 THEN 'Partial Copay'
                ELSE NULL
            END AS copay_note
        FROM combined
        {"WHERE UPPER(client_name) = UPPER('" + sel_client + "')" if sel_client != "All" else ""}
        ORDER BY client_name, yr, mo
    """).df()

    if status_df.empty:
        st.info("No copay data found for the selected filters.")
    else:
        # Build HTML table with badges
        rows_html = ""
        for _, row in status_df.iterrows():
            badge = _status_badge(row["copay_status"], row["copay_note"])
            pending_color = ""
            if row["copay_note"] == "Copay":
                pending_color = f'color:{COPAY_COLOR};font-weight:700'
            elif row["copay_note"] == "Exceeds Copay":
                pending_color = f'color:{EXCEED_COLOR};font-weight:700'
            elif row["copay_note"] == "Partial Copay":
                pending_color = f'color:{PARTIAL_COLOR};font-weight:700'
            elif row["copay_status"] == "Good" and not row["copay_note"]:
                pending_color = f'color:{PAID_COLOR};font-weight:700'

            rows_html += f"""
            <tr>
              <td>{row["client_name"]}</td>
              <td style="text-align:right">${row["copay_amount"]:,.2f}</td>
              <td>{row["month_label"]}</td>
              <td style="text-align:right">${row["billed_dollars"]:,.2f}</td>
              <td style="text-align:right">${row["paid_dollars"]:,.2f}</td>
              <td style="text-align:right;{pending_color}">${row["pending_dollars"]:,.2f}</td>
              <td style="text-align:center">{badge}</td>
            </tr>"""

        html = f"""
        <style>
          .copay-table {{ width:100%;border-collapse:collapse;font-size:0.87em }}
          .copay-table th {{ background:#263044;color:#cdd6f4;padding:8px 12px;text-align:left;border-bottom:2px solid #45475a }}
          .copay-table td {{ padding:6px 12px;border-bottom:1px solid #313244;vertical-align:middle }}
          .copay-table tr:hover td {{ background:#1e2130 }}
        </style>
        <table class="copay-table">
          <thead><tr>
            <th>Client</th><th style="text-align:right">Monthly Copay</th><th>Month</th>
            <th style="text-align:right">Billed $</th><th style="text-align:right">Paid $</th>
            <th style="text-align:right">Pending $</th><th style="text-align:center">Status</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        """
        st.markdown(html, unsafe_allow_html=True)

        # Summary metrics
        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Clients", status_df["client_name"].nunique())
        m2.metric("✦ Copay (Expected)",   int((status_df["copay_note"] == "Copay").sum()))
        m3.metric("⚠ Exceeds Copay",      int((status_df["copay_note"] == "Exceeds Copay").sum()))
        m4.metric("✓ Paid in Full",        int((status_df["copay_status"] == "Good") & (status_df["copay_note"].isna()).sum()))
