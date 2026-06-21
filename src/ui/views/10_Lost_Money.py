"""
src/ui/views/10_Lost_Money.py
Dedicated view for tracking revenue written off as Lost Money.
"""

from __future__ import annotations
import pandas as pd
import streamlit as st

from src.ui.components.filters import _get_conn

# ── Page Configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Lost Money Tracker",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <div style='margin-bottom:1rem;'>
        <h1 style='margin:0;font-size:1.8rem;font-weight:700;color:#e8eaf0;'>
            💸 Lost Money Tracker
        </h1>
        <p style='color:#a0a0b0;margin-top:0.2rem;font-size:0.95rem;'>
            Financial forensics view tracking all claims explicitly overridden and written off as Lost Money.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()

# Fetch all overridden claims categorized as "Lost Money"
query = """
    SELECT 
        t.client_name,
        t.payer,
        t.first_dos,
        t.last_dos,
        t.pending_hours,
        t.override_reason,
        t.overridden_by,
        t.override_date,
        t.notes,
        r.care_type
    FROM unskilled_remit_tracker t
    LEFT JOIN reconciliation r 
      ON t.client_name = r.client_name_payroll 
     AND t.first_dos = r.week_start_date
    WHERE t.override = TRUE 
      AND t.override_reason LIKE 'Lost Money%'
    ORDER BY t.override_date DESC
"""

try:
    df = conn.execute(query).df()
except Exception as e:
    st.error(f"Failed to load Lost Money data: {e}")
    st.stop()

if df.empty:
    st.success("🎉 No claims have been written off as Lost Money!")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
# Approximate lost revenue using a standard rate if exact rate isn't available
# Average Unskilled Rate is ~$23.11, Skilled is ~$54.66. We'll blend it or show hours.
total_hours_lost = df['pending_hours'].sum()
total_claims_lost = len(df)
# Estimate revenue (assuming mostly unskilled at $23.11)
est_revenue_lost = total_hours_lost * 23.11

col1, col2, col3 = st.columns(3)
col1.metric("Total Hours Lost", f"{total_hours_lost:,.2f} hrs")
col2.metric("Total Claims Written Off", f"{total_claims_lost:,}")
col3.metric("Est. Revenue Lost", f"${est_revenue_lost:,.2f}")

st.divider()

# ── Data Grid ─────────────────────────────────────────────────────────────────
st.subheader("📋 Lost Money Ledger")

# Formatting for display
display_df = df.copy()
display_df["first_dos"] = pd.to_datetime(display_df["first_dos"]).dt.strftime('%Y-%m-%d')
display_df["last_dos"] = pd.to_datetime(display_df["last_dos"]).dt.strftime('%Y-%m-%d')
display_df["override_date"] = pd.to_datetime(display_df["override_date"]).dt.strftime('%Y-%m-%d')

display_df.columns = [
    "Client", "Payer", "First DOS", "Last DOS", "Hours Lost",
    "Reason Detail", "Analyst", "Override Date", "Analyst Notes", "Care Type"
]

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Hours Lost": st.column_config.NumberColumn("Hours Lost", format="%.2f"),
        "Client": st.column_config.TextColumn("Client", width="medium"),
        "Reason Detail": st.column_config.TextColumn("Reason Detail", width="large"),
        "Analyst Notes": st.column_config.TextColumn("Analyst Notes", width="large"),
    }
)
