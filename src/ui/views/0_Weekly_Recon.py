"""
src/ui/pages/0_Weekly_Recon.py
Weekly Reconciliation — Excel-style view.
For a selected week: one row per client, payroll/billed/paid/pending hours,
sorted by pending hours descending (largest shortfall first).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st



from src.ui.styles.theme import inject_css
from src.ui.components.filters import week_filter, insurance_filter, _get_conn
from src.db import queries

inject_css()

conn = _get_conn()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>
            📋 Weekly Reconciliation
        </h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Excel-style view · one row per client · payroll vs billed vs paid · sorted by pending ↓
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar filters ─────────────────────────────────────────────────────────
st.sidebar.markdown("**Filters**")
client_options = ["All Clients"] + queries.all_clients(conn)
selected_client = st.sidebar.selectbox("🔍 Client Name", options=client_options, index=0, key="wr_client_name")
show_archived_val = st.session_state.get("wr_show_archived", False)
week    = week_filter("wr_week", show_archived=show_archived_val)
ins     = insurance_filter("wr_ins")
fu_only = st.sidebar.toggle("Follow-Up Only", value=False, key="wr_fu_only")
show_archived = st.sidebar.checkbox("Show Archived (Older than 1 year and 1 week)", value=False, key="wr_show_archived")

# ── Load data ───────────────────────────────────────────────────────────────
df = queries.weekly_recon_detail(
    conn,
    week_start=week,
    insurance=ins if ins else None,
    follow_up_only=fu_only,
)

# Apply Archive filter (hide rows older than 1 year & 1 week by default)
if not show_archived:
    import datetime
    one_year_and_week_ago = (datetime.date.today() - datetime.timedelta(days=372)).strftime("%Y-%m-%d")
    df = df[df["week_start"] >= one_year_and_week_ago]

# Apply Client Name filter
if selected_client != "All Clients":
    df = df[df["client"] == selected_client]

if df.empty:
    st.info("No reconciliation data for the selected filters. Run the ETL pipeline or adjust filters.", icon="ℹ️")
    st.stop()

# ── Summary bar ─────────────────────────────────────────────────────────────
total_payroll = df["payroll_hours"].sum()
total_billed  = df["billed_hours"].sum()
total_paid    = df["paid_hours"].sum()
total_pending = max(total_payroll - total_paid, 0.0)
n_followup    = (df["status"] == "Follow up").sum()
n_good        = (df["status"] == "Good").sum()

# Show week range if a specific week is selected
if week:
    ws = pd.to_datetime(week).strftime("%b %d")
    if not df.empty and "week_end" in df.columns:
        we = pd.to_datetime(df["week_end"].iloc[0]).strftime("%b %d, %Y")
        week_label = f"{ws} – {we}"
    else:
        week_label = f"{ws}"
else:
    week_label = "All Weeks"

st.markdown(
    f"""
    <div style='background:linear-gradient(135deg,#1e2130,#252840);
                border:1px solid #2a2d3e;border-radius:12px;
                padding:16px 24px;margin-bottom:1.2rem;
                display:flex;gap:32px;flex-wrap:wrap;align-items:center;'>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Period</div>
            <div style='font-size:1rem;font-weight:700;color:#4f8ef7;margin-top:2px;'>{week_label}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Clients</div>
            <div style='font-size:1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{len(df):,}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Payroll Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#e8eaf0;margin-top:2px;'>{total_payroll:,.1f}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Billed Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#a78bfa;margin-top:2px;'>{total_billed:,.1f}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>Paid Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#22c55e;margin-top:2px;'>{total_paid:,.1f}</div>
        </div>
        <div>
            <div style='font-size:0.68rem;color:#8892a4;text-transform:uppercase;letter-spacing:.08em;'>⏳ Pending Hrs</div>
            <div style='font-size:1rem;font-weight:700;color:#f59e0b;margin-top:2px;'>{total_pending:,.1f}</div>
        </div>
        <div style='margin-left:auto;display:flex;gap:16px;'>
            <div style='text-align:center;'>
                <div style='font-size:1.2rem;font-weight:700;color:#22c55e;'>{n_good}</div>
                <div style='font-size:0.68rem;color:#8892a4;'>✅ Good</div>
            </div>
            <div style='text-align:center;'>
                <div style='font-size:1.2rem;font-weight:700;color:#f59e0b;'>{n_followup}</div>
                <div style='font-size:0.68rem;color:#8892a4;'>⚠️ Follow-up</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Build display columns ───────────────────────────────────────────────────
display = df.copy()

# Format date range into one readable column starting with YYYY-MM-DD for chronological sorting
display["week_range"] = (
    pd.to_datetime(display["week_start"]).dt.strftime("%Y-%m-%d")
    + " ("
    + pd.to_datetime(display["week_start"]).dt.strftime("%b %d")
    + " – "
    + pd.to_datetime(display["week_end"]).dt.strftime("%b %d")
    + ")"
)

show_cols = [
    "insurance", "client", "week_range",
    "payroll_hours", "billed_hours", "paid_hours",
    "pending_hrs", "payroll_vs_billed",
    "status", "reason",
    "is_copay_client",
]
show_cols = [c for c in show_cols if c in display.columns]

# ── Status colour indicator column ─────────────────────────────────────────
STATUS_ICON = {"Good": "✅", "Follow up": "⚠️", "No Payroll Hours": "⬜", "No Payroll Data": "⬜"}
display["status"] = display["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}" if isinstance(s, str) else s)

# ── Render table ────────────────────────────────────────────────────────────
selection = st.dataframe(
    display[show_cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "insurance":         st.column_config.TextColumn("Insurance",    width="small"),
        "client":            st.column_config.TextColumn("Client",       width="medium"),
        "week_range":        st.column_config.TextColumn("Week",         width="medium"),
        "payroll_hours":     st.column_config.NumberColumn("Payroll Hrs",format="%.1f"),
        "billed_hours":      st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
        "paid_hours":        st.column_config.NumberColumn("Paid Hrs",   format="%.1f"),
        "pending_hrs":       st.column_config.NumberColumn("⏳ Pending", format="%.1f"),
        "payroll_vs_billed": st.column_config.NumberColumn("PvB Δ",      format="%.1f"),
        "status":            st.column_config.TextColumn("Status",       width="small"),
        "reason":            st.column_config.TextColumn("Reason",       width="medium"),
        "is_copay_client":   st.column_config.CheckboxColumn("Copay",    width="small"),
    },
    on_select="rerun",
    selection_mode="single-row",
    key="weekly_recon_selection",
    height=min(60 + len(display) * 35, 400),
)

st.caption(
    f"📊 {len(display):,} clients · sorted by ⏳ Pending hrs ↓ · "
    f"PvB Δ = Payroll vs Billed difference · Click any row to view individual claim details below"
)

# ── Render totals row for the entire week ───────────────────────────────────
st.markdown(
    f"""
    <div style='background:#13151f;border:1px solid #2a2d3e;border-radius:8px;
                padding:12px 20px;margin-top:8px;font-size:0.82rem;
                display:flex;gap:32px;flex-wrap:wrap;'>
        <span style='color:#8892a4;font-weight:600;text-transform:uppercase;letter-spacing:.06em;'>TOTALS (ALL CLIENTS)</span>
        <span>Payroll: <b style='color:#e8eaf0;'>{total_payroll:,.1f}</b></span>
        <span>Billed: <b style='color:#a78bfa;'>{total_billed:,.1f}</b></span>
        <span>Paid: <b style='color:#22c55e;'>{total_paid:,.1f}</b></span>
        <span>Pending: <b style='color:#f59e0b;'>{total_pending:,.1f}</b></span>
        <span>PvB Δ: <b style='color:#e8eaf0;'>{(total_payroll - total_billed):,.1f}</b></span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Render selected client details ──────────────────────────────────────────
selected_rows = selection.selection.rows if selection.selection else []
if selected_rows:
    selected_row = display.iloc[selected_rows[0]]
    client_name = selected_row["client"]
    w_start = selected_row["week_start"]
    w_end = selected_row["week_end"]
    
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class='section-header'>
            <h3>🔍 Remittance Claim Details: {client_name} (Service Week: {selected_row['week_range']})</h3>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Try with remittance name matching
    rem_name = client_name
    summary_df = queries.client_summary(conn, client_name)
    if not summary_df.empty and "client_name_remittance" in summary_df.columns:
        alt = summary_df.iloc[0].get("client_name_remittance")
        if alt:
            rem_name = alt

    rem_df = queries.client_ledger(conn, rem_name, start_date=w_start, end_date=w_end)
    if rem_df.empty:
        rem_df = queries.client_ledger(conn, client_name, start_date=w_start, end_date=w_end)

    if rem_df.empty:
        st.info("ℹ️ No claim-level remittance records found for this client during this service week.", icon="ℹ️")
    else:
        # Calculate deltas for dollars
        rem_df["amt_delta"] = rem_df["charge_amount"] - rem_df["payment_amount"]
        
        def compute_rec_status(row):
            b_hrs = row.get("billed_hours", 0) or 0
            p_hrs = row.get("paid_hours", 0) or 0
            b_amt = row.get("charge_amount", 0) or 0
            p_amt = row.get("payment_amount", 0) or 0
            
            if p_hrs < 0 or p_amt < 0:
                return "Reversal"
            if b_hrs > 0:
                if p_hrs >= b_hrs:
                    return "Paid in Full"
                elif p_hrs == 0:
                    return "Denial / Unpaid"
                else:
                    return "Short Paid"
            if b_amt > 0:
                if p_amt >= b_amt:
                    return "Paid in Full"
                elif p_amt == 0:
                    return "Denial / Unpaid"
                else:
                    return "Short Paid"
            return "Unknown"

        rem_df["reconciled_status"] = rem_df.apply(compute_rec_status, axis=1)

        display_cols = [c for c in [
            "first_dos", "last_dos", "payment_date",
            "reconciled_status", "charge_amount", "payment_amount", "amt_delta",
            "billed_hours", "paid_hours", "tcn",
        ] if c in rem_df.columns]

        st.dataframe(
            rem_df[display_cols],
            use_container_width=True,
            hide_index=True,
            height=(len(rem_df) + 1) * 35 + 3,
            column_config={
                "first_dos":         st.column_config.DateColumn("First DOS"),
                "last_dos":          st.column_config.DateColumn("Last DOS"),
                "payment_date":      st.column_config.DateColumn("Payment Date"),
                "reconciled_status": st.column_config.TextColumn("Status", width="medium"),
                "charge_amount":     st.column_config.NumberColumn("Charged Amt", format="$%.2f"),
                "payment_amount":    st.column_config.NumberColumn("Paid Amt", format="$%.2f"),
                "amt_delta":         st.column_config.NumberColumn("$ Delta", format="$%.2f"),
                "billed_hours":      st.column_config.NumberColumn("Billed Hrs", format="%.1f"),
                "paid_hours":        st.column_config.NumberColumn("Paid Hrs", format="%.1f"),
                "tcn":               st.column_config.TextColumn("Check/EFT # (TCN)", width="medium"),
            },
        )

        # Calculate selected client totals
        total_charged = rem_df["charge_amount"].sum()
        total_paid = rem_df["payment_amount"].sum()
        total_delta = rem_df["amt_delta"].sum()
        total_billed_h = rem_df["billed_hours"].sum()
        total_paid_h = rem_df["paid_hours"].sum()

        st.markdown(
            f"""
            <div style='background:#13151f;border:1px solid #2a2d3e;border-radius:8px;
                        padding:12px 20px;margin-top:8px;font-size:0.82rem;
                        display:flex;gap:24px;flex-wrap:wrap;'>
                <span style='color:#8892a4;font-weight:600;text-transform:uppercase;letter-spacing:.06em;'>TOTALS ({client_name})</span>
                <span>Billed Hrs: <b style='color:#e8eaf0;'>{total_billed_h:,.1f}</b></span>
                <span>Paid Hrs: <b style='color:#22c55e;'>{total_paid_h:,.1f}</b></span>
                <span>Charged $: <b style='color:#a78bfa;'>${total_charged:,.2f}</b></span>
                <span>Paid $: <b style='color:#22c55e;'>${total_paid:,.2f}</b></span>
                <span>$ Delta: <b style='color:{"#e8eaf0" if total_delta == 0 else "#ef4444"};'>${total_delta:,.2f}</b></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
