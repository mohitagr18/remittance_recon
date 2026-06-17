"""
src/ui/views/7_Copay_Manager.py
Copay Management & Reconciliation page.

Two tabs:
  1. Copay Status  — monthly pending vs copay per client, with distinct
     purple "Copay Paid" highlight when pending ≈ copay_amount
  2. Manage Copays — CRUD panel to update amounts and effective dates
"""
from __future__ import annotations
import streamlit as st
import duckdb
import pandas as pd
from pathlib import Path

_DB = Path(__file__).parent.parent.parent.parent / "data" / "recon.duckdb"

@st.cache_resource
def _conn():
    return duckdb.connect(str(_DB))


# ── Business logic ─────────────────────────────────────────────────────────────

COPAY_TOL = 1.00

STATUS_CONFIG = {
    "Copay Paid":    {"icon": "💜", "color": "#a78bfa", "bg": "#1e1535"},
    "Fully Paid":    {"icon": "✅", "color": "#22c55e", "bg": "#0d2318"},
    "Exceeds Copay": {"icon": "⚠️",  "color": "#f59e0b", "bg": "#1f1a0d"},
    "Partial Copay": {"icon": "🔶", "color": "#f97316", "bg": "#1f1208"},
    "Follow Up":     {"icon": "🔴", "color": "#ef4444", "bg": "#1f0d0d"},
}


def _status(pending: float, copay: float) -> str:
    if abs(pending) <= COPAY_TOL:
        return "Fully Paid"
    if abs(pending - copay) <= COPAY_TOL:
        return "Copay Paid"
    if pending > copay + COPAY_TOL:
        return "Exceeds Copay"
    if 0 < pending < copay - COPAY_TOL:
        return "Partial Copay"
    return "Follow Up"


# ── Data loaders ───────────────────────────────────────────────────────────────

def _load_status() -> pd.DataFrame:
    sql = """
        WITH cc AS (
            SELECT id, client_name, copay_amount
            FROM copay_clients
            WHERE is_active = TRUE AND copay_amount IS NOT NULL
        ),
        monthly AS (
            SELECT
                r.client_name_payroll                           AS client_name,
                cc.copay_amount,
                DATE_PART('year',  r.week_start_date)::INT     AS yr,
                DATE_PART('month', r.week_start_date)::INT     AS mo,
                STRFTIME(MAKE_DATE(
                    DATE_PART('year',  r.week_start_date)::INT,
                    DATE_PART('month', r.week_start_date)::INT, 1
                ), '%b %Y')                                     AS month_label,
                ROUND(COALESCE(SUM(rem.charge_amount),   0), 2) AS total_billed,
                ROUND(COALESCE(SUM(rem.payment_amount),  0), 2) AS total_paid
            FROM reconciliation r
            JOIN cc ON UPPER(cc.client_name) = UPPER(r.client_name_payroll)
            LEFT JOIN remittance rem
                ON UPPER(rem.client_name_combined) = UPPER(r.client_name_payroll)
               AND rem.is_latest = TRUE
               AND DATE_PART('year',  rem.first_dos)::INT = DATE_PART('year',  r.week_start_date)::INT
               AND DATE_PART('month', rem.first_dos)::INT = DATE_PART('month', r.week_start_date)::INT
            GROUP BY r.client_name_payroll, cc.copay_amount,
                     DATE_PART('year',  r.week_start_date)::INT,
                     DATE_PART('month', r.week_start_date)::INT
        )
        SELECT
            client_name, copay_amount, month_label, yr, mo,
            total_billed, total_paid,
            ROUND(total_billed - total_paid, 2) AS pending
        FROM monthly
        ORDER BY client_name, yr, mo
    """
    return _conn().execute(sql).df()


def _load_clients() -> pd.DataFrame:
    return _conn().execute("""
        SELECT id, client_name, copay_amount, effective_from, effective_to, is_active, updated_at
        FROM copay_clients ORDER BY client_name
    """).df()


# ── HTML helpers ───────────────────────────────────────────────────────────────

def _badge(label: str) -> str:
    cfg = STATUS_CONFIG.get(label, {"icon": "❓", "color": "#8892a4", "bg": "#1e2130"})
    return (
        f'<span style="background:{cfg["bg"]};color:{cfg["color"]};'
        f'border:1px solid {cfg["color"]};border-radius:6px;'
        f'padding:2px 10px;font-size:0.8rem;font-weight:600;white-space:nowrap;">'
        f'{cfg["icon"]} {label}</span>'
    )


def _row_html(row: pd.Series) -> str:
    status = _status(row["pending"], row["copay_amount"])
    cfg    = STATUS_CONFIG.get(status, {"color": "#8892a4", "bg": "#1e2130"})
    is_copay = (status == "Copay Paid")
    border = f'2px solid {cfg["color"]}' if is_copay else '1px solid #2a2d3e'
    bg     = cfg["bg"] if is_copay else "#1e2130"
    glow   = f'box-shadow:0 0 12px {cfg["color"]}44;' if is_copay else ''
    return (
        f'<div style="background:{bg};border:{border};{glow}border-radius:10px;'
        f'padding:12px 18px;margin-bottom:8px;display:flex;align-items:center;gap:20px;flex-wrap:wrap;">'
        f'<div style="min-width:200px;font-weight:600;color:#e8eaf0;">{row["client_name"]}</div>'
        f'<div style="min-width:80px;color:#8892a4;font-size:0.85rem;">{row["month_label"]}</div>'
        f'<div style="min-width:100px;color:#c8cfe0;">Billed: <b>${row["total_billed"]:,.2f}</b></div>'
        f'<div style="min-width:100px;color:#c8cfe0;">Paid: <b>${row["total_paid"]:,.2f}</b></div>'
        f'<div style="min-width:100px;color:#c8cfe0;">Pending: <b>${row["pending"]:,.2f}</b></div>'
        f'<div style="min-width:100px;color:#8892a4;font-size:0.8rem;">Copay: ${row["copay_amount"]:,.2f}/mo</div>'
        f'<div>{_badge(status)}</div>'
        f'</div>'
    )


# ── Page ───────────────────────────────────────────────────────────────────────

def main():
    from src.ui.styles.theme import inject_css
    inject_css()

    st.title("💜 Copay Manager")
    st.caption("Monthly copay reconciliation — pending ≈ copay means the client owes their share and is shown in purple.")

    tab1, tab2 = st.tabs(["📊 Copay Status", "⚙️ Manage Copays"])

    # ── Tab 1: Status view ─────────────────────────────────────────────────────
    with tab1:
        df = _load_status()

        if df.empty:
            st.info("No copay data found. Ensure copay_clients has amounts and reconciliation data exists.")
            return

        df["status"] = df.apply(lambda r: _status(r["pending"], r["copay_amount"]), axis=1)

        # KPI summary row
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Client-Months", len(df))
        k2.metric("💜 Copay Paid",   int((df["status"] == "Copay Paid").sum()),
                  help="Pending ≈ monthly copay — expected and correct")
        k3.metric("✅ Fully Paid",   int((df["status"] == "Fully Paid").sum()),
                  help="Pending = $0")
        k4.metric("⚠️ Needs Review", int(df["status"].isin(["Exceeds Copay","Partial Copay","Follow Up"]).sum()),
                  help="Exceeds copay or partial underpayment")

        st.markdown("---")

        # Legend
        st.markdown(
            '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:1rem;">' +
            ' '.join(_badge(s) for s in STATUS_CONFIG) +
            '</div>',
            unsafe_allow_html=True
        )

        # Filters
        c1, c2, c3 = st.columns([2, 2, 1])
        sel_client = c1.selectbox("Client", ["All"] + sorted(df["client_name"].unique().tolist()))
        month_opts = sorted(df["month_label"].unique().tolist(),
                            key=lambda x: (int(x.split()[1]),
                                           ["Jan","Feb","Mar","Apr","May","Jun",
                                            "Jul","Aug","Sep","Oct","Nov","Dec"].index(x.split()[0])))
        sel_month  = c2.selectbox("Month", ["All"] + month_opts)
        copay_only = c3.checkbox("Copay only", value=False)

        fdf = df.copy()
        if sel_client != "All":
            fdf = fdf[fdf["client_name"] == sel_client]
        if sel_month != "All":
            fdf = fdf[fdf["month_label"] == sel_month]
        if copay_only:
            fdf = fdf[fdf["status"] == "Copay Paid"]

        st.markdown(f"**{len(fdf)} records**")
        st.markdown("".join(_row_html(r) for _, r in fdf.iterrows()), unsafe_allow_html=True)

    # ── Tab 2: Manage copay amounts & dates ────────────────────────────────────
    with tab2:
        st.subheader("Copay Client Management")
        st.caption("Update monthly copay amounts and effective date ranges. Leave dates blank if unknown.")

        clients_df = _load_clients()

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
                        _conn().execute("""
                            UPDATE copay_clients
                            SET copay_amount   = ?,
                                effective_from = CAST(? AS DATE),
                                effective_to   = CAST(? AS DATE),
                                is_active      = ?,
                                updated_at     = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, [new_amt,
                              str(eff_from) if eff_from else None,
                              str(eff_to)   if eff_to   else None,
                              active, int(row["id"])])
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
            if st.form_submit_button("➕ Add"):
                if new_name.strip():
                    max_id = _conn().execute("SELECT COALESCE(MAX(id),0) FROM copay_clients").fetchone()[0]
                    _conn().execute("""
                        INSERT INTO copay_clients
                            (id, client_name, is_active, copay_amount, effective_from, effective_to, updated_at)
                        VALUES (?, ?, TRUE, ?, CAST(? AS DATE), CAST(? AS DATE), CURRENT_TIMESTAMP)
                    """, [max_id + 1, new_name.strip().upper(), new_copay,
                          str(nf) if nf else None, str(nt) if nt else None])
                    st.success(f"✅ Added {new_name.strip().upper()} — ${new_copay:,.2f}/mo")
                    st.rerun()
                else:
                    st.error("Client name is required.")


if __name__ == "__main__":
    main()
