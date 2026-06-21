"""
src/ui/views/8_Unskilled_Remittance_Tracker.py
Unskilled Remittance Tracker — Analyst view + Executive dashboard.
(Forced reload 2)
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.config import cfg
from src.ui.components.filters import _get_conn
from src.db.unskilled_tracker_queries import (
    ANALYST_OPTIONS,
    add_comment,
    get_aged_items,
    get_comments,
    get_escalation_by_client,
    get_kpis,
    get_pending_df,
    get_resolved_df,
    reopen_resolved_row,
    refresh_escalation_flags,
    save_rebill_attempt,
    sync_payments_from_remittance,
    sync_pending_from_reconciliation,
    resolve_copay_clients,
)

st.set_page_config(
    page_title="Unskilled Remittance Tracker",
    page_icon="💰",
    layout="wide",
)

# ── Status badge colours ───────────────────────────────────────────────────────
_BADGE = {
    "PENDING":   ("🟡", "#fff3cd"),
    "PARTIAL":   ("🟠", "#fde8d8"),
    "ESCALATED": ("🔴", "#fde8d8"),
    "RESOLVED":  ("🟢", "#d4edda"),
}


def _badge(status: str) -> str:
    icon, _ = _BADGE.get(status, ("⚪", "#eee"))
    return f"{icon} {status.title()}"


# ── DB connection (cached per session) ────────────────────────────────────────
@st.cache_resource
def _conn():  # DELETED
    pass  # unused
conn = _get_conn()


# ══════════════════════════════════════════════════════════════════════════════
# SYNC HELPER (runs on every page load)
# ══════════════════════════════════════════════════════════════════════════════

def _run_sync() -> None:
    """Sync new pending rows + update payments + refresh escalation flags."""
    sync_pending_from_reconciliation(conn)
    sync_payments_from_remittance(conn)
    refresh_escalation_flags(conn)
    resolve_copay_clients(conn)


_run_sync()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER + ROLE SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

st.title("💰 Unskilled Remittance Tracker")

role = st.radio(
    "View as:",
    ["Analyst", "Executive"],
    horizontal=True,
    label_visibility="collapsed",
)

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# ── EXECUTIVE VIEW ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

if role == "Executive":
    kpis = get_kpis(conn)

    # KPI strip
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Open Claims",        kpis["total_open"])
    c2.metric("Pending Hours",      f"{kpis['total_pending_hours']:.1f}")
    c3.metric("Escalated",          kpis["escalated_count"],  delta_color="inverse")
    c4.metric("Partial Payments",   kpis["partial_count"])
    c5.metric("Avg Days Open",      f"{kpis['avg_days_open']}d")
    c6.metric("Resolved This Month",kpis["resolved_this_month"])

    st.divider()

    # Escalation breakdown
    st.subheader("🔴 Escalated Clients")
    esc_tab1, esc_tab2 = st.tabs(["By Client", "By Age"])

    with esc_tab1:
        esc_df = get_escalation_by_client(conn)
        if esc_df.empty:
            st.info("No escalated clients.")
        else:
            st.dataframe(
                esc_df.rename(columns={
                    "client_name": "Client",
                    "payer": "Payer",
                    "open_entries": "Open Entries",
                    "total_pending_hours": "Pending Hrs",
                    "oldest_entry": "Oldest Entry",
                    "days_outstanding": "Days Open",
                    "reasons": "Reason",
                }),
                use_container_width=True,
                hide_index=True,
            )

    with esc_tab2:
        aged_df = get_aged_items(conn)
        if aged_df.empty:
            st.info("No age-escalated items.")
        else:
            st.dataframe(
                aged_df.rename(columns={
                    "client_name": "Client",
                    "payer": "Payer",
                    "first_dos": "First DOS",
                    "last_dos": "Last DOS",
                    "pending_hours": "Pending Hrs",
                    "entry_date": "Entry Date",
                    "days_outstanding": "Days Open",
                }),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    # Full pending grid (read-only)
    st.subheader("📋 All Pending Items")
    pending_df = get_pending_df(conn)
    if pending_df.empty:
        st.info("No pending items.")
    else:
        display = pending_df[[
            "client_name", "payer", "first_dos", "last_dos",
            "regular_hours", "respite_hours", "pending_hours",
            "rebill1_date", "rebill2_date", "rebill3_date",
            "status", "entry_date", "comment_count",
        ]].copy()
        display["status"] = display["status"].apply(_badge)
        display.columns = [
            "Client", "Payer", "First DOS", "Last DOS",
            "Reg Hrs", "Resp Hrs", "Pending Hrs",
            "Rebill 1", "Rebill 2", "Rebill 3",
            "Status", "Entry Date", "💬",
        ]
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.stop()  # Executive view ends here


# ══════════════════════════════════════════════════════════════════════════════
# ── ANALYST VIEW ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Active Analyst Dropdown
analysts_df = conn.execute("SELECT name FROM analysts WHERE is_active = TRUE").df()
analyst_list = analysts_df["name"].tolist() if not analysts_df.empty else ["Unknown Analyst"]

col_a1, col_a2 = st.columns([1, 4])
with col_a1:
    current_analyst = st.session_state.get("active_analyst", analyst_list[0] if analyst_list else "Unknown")
    # Make sure current_analyst is in the list, otherwise append it so selectbox doesn't crash
    if current_analyst not in analyst_list:
        analyst_list.insert(0, current_analyst)
        
    selected_analyst = st.selectbox("👤 Analyst Login", analyst_list, index=analyst_list.index(current_analyst), key="analyst_login")
    st.session_state["active_analyst"] = selected_analyst


# 2. Get combined pending & resolved data
pending_df = get_pending_df(conn)
resolved_df = get_resolved_df(conn)
combined_df = pd.concat([pending_df, resolved_df]).drop_duplicates(subset=["id"])

# Filter out records older than 1 year and 1 week
if not combined_df.empty:
    cutoff_date = pd.Timestamp.now().normalize() - pd.DateOffset(years=1, weeks=1)
    combined_df = combined_df[pd.to_datetime(combined_df["first_dos"]) >= cutoff_date]

# 3. Escalation Banner (reads from combined_df to find active escalated ones)
if not combined_df.empty:
    escalated_df = combined_df[(combined_df["is_escalated"] == True) & (combined_df["override"] == False) & (combined_df["status"] != "RESOLVED") & (combined_df["resolved"] == False)]
else:
    escalated_df = pd.DataFrame()

if not escalated_df.empty:
    st.error(f"🔴 ESCALATION ALERT — {len(escalated_df)} item(s) require immediate attention (Volume >= 5 in 2mo window, or age >= 10mo)")

# 4. Filters & Controls
col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([1.5, 1.5, 1.5, 1.2, 2.3])
with col_f1:
    search = st.text_input("🔍 Search client", placeholder="Type client name…", key="unskilled_search")
with col_f2:
    payers = ["All"] + sorted(combined_df["payer"].dropna().unique().tolist()) if not combined_df.empty else ["All"]
    payer_f = st.selectbox("Payer", payers, key="unskilled_payer")
with col_f3:
    statuses = ["PENDING", "ESCALATED", "PARTIAL", "All", "RESOLVED", "OVERRIDDEN"]
    status_f = st.selectbox("Status Filter", statuses, key="unskilled_status")
with col_f4:
    months = ["All"]
    if not combined_df.empty:
        month_series = pd.to_datetime(combined_df["first_dos"]).dt.to_period('M').dropna().unique()
        month_series_sorted = sorted(month_series, reverse=True)
        months += [m.strftime('%B %Y') for m in month_series_sorted]
    month_f = st.selectbox("Month", months, key="unskilled_month")
with col_f5:
    week_f = "All"
    if month_f != "All":
        m_df = combined_df[pd.to_datetime(combined_df["first_dos"]).dt.strftime('%B %Y') == month_f]
        if not m_df.empty:
            weeks_data = m_df[["first_dos", "last_dos"]].drop_duplicates().sort_values("first_dos", ascending=False)
            week_options = ["All"]
            for _, row in weeks_data.iterrows():
                fd = pd.to_datetime(row["first_dos"]).strftime('%m/%d/%Y')
                ld = pd.to_datetime(row["last_dos"]).strftime('%m/%d/%Y')
                week_options.append(f"{fd} - {ld}")
            week_f = st.selectbox("Week", week_options, key="unskilled_week")
        else:
            st.selectbox("Week", ["All"], disabled=True, key="unskilled_week_dis1")
    else:
        st.selectbox("Week", ["Select a month first"], disabled=True, key="unskilled_week_dis2")

# Trigger pending override modal if exists - REMOVED


# Apply filters
df = combined_df.copy()
if not df.empty:
    if search:
        df = df[df["client_name"].str.contains(search, case=False, na=False)]
    if payer_f != "All":
        df = df[df["payer"] == payer_f]
    if status_f != "All":
        if status_f == "OVERRIDDEN":
            df = df[df["override"] == True]
        else:
            df = df[df["status"] == status_f]
    if month_f != "All":
        df = df[pd.to_datetime(df["first_dos"]).dt.strftime('%B %Y') == month_f]
    if week_f not in ("All", "Select a month first"):
        fd_str, ld_str = week_f.split(" - ")
        start_dt = pd.to_datetime(fd_str)
        end_dt = pd.to_datetime(ld_str)
        df = df[(pd.to_datetime(df["first_dos"]) == start_dt) & (pd.to_datetime(df["last_dos"]) == end_dt)]

# Generate visual badges
def make_badge(row):
    if row["override"]:
        return "🔒 Override"
    elif row["resolved"] or row["status"] == "RESOLVED":
        return "🟢 Resolved"
    elif row["is_escalated"] or row["status"] == "ESCALATED":
        return "🔴 Escalated"
    elif row["status"] == "PARTIAL":
        return "🟠 Partial"
    else:
        return "🟡 Pending"

if not df.empty:
    df["status_badge"] = df.apply(make_badge, axis=1)
    
    # Sort: Escalated & Open first, then Pending, then Overridden, then Resolved
    def sort_rank(row):
        if row["override"]:
            return 3
        elif row["resolved"] or row["status"] == "RESOLVED":
            return 4
        elif row["is_escalated"] or row["status"] == "ESCALATED":
            return 1
        else:
            return 2
    df["rank"] = df.apply(sort_rank, axis=1)
    df = df.sort_values(["rank", "first_dos"], ascending=[True, True])
    # Don't set id as index, keep it as a column for safe positional lookup
    # df.set_index("id", inplace=True)
    
    # Keep and format required columns
    display_cols = [
        "status_badge", "client_name", "payer", "first_dos", "last_dos",
        "regular_hours", "respite_hours", "pending_hours",
        "notes", "override_reason", "override", "follow_up_date"
    ]
    df_display = df[display_cols].copy()
    
    # Guard all NaT/NaN/None values for Streamlit
    for col in ["first_dos", "last_dos", "follow_up_date"]:
        df_display[col] = df_display[col].apply(lambda x: None if pd.isna(x) else x)
        
    df_display["regular_hours"] = df_display["regular_hours"].fillna(0.0).astype(float)
    df_display["respite_hours"] = df_display["respite_hours"].fillna(0.0).astype(float)
    df_display["pending_hours"] = df_display["pending_hours"].fillna(0.0).astype(float)
    df_display["notes"] = df_display["notes"].fillna("")
    df_display["override_reason"] = df_display["override_reason"].fillna("")

    # Reset index to ensure clean positional indexing (0, 1, 2...) for st.data_editor
    df_display = df_display.reset_index(drop=True)

    # 1. On-change persistence flow
    state_key = "unskilled_tracker_editor"
    if state_key in st.session_state:
        edits = st.session_state[state_key].get("edited_rows", {})
        if edits:
            id_map = st.session_state.get("unskilled_tracker_ids", [])
            for str_pos, changes in edits.items():
                pos = int(str_pos)
                if pos < len(id_map):
                    tracker_id = id_map[pos]
                else:
                    tracker_id = int(df.iloc[pos]["id"]) if "id" in df.columns else int(df.index[pos])
                
                # DEBUG LOGGING
                with open("debug_edits.log", "a") as f_dbg:
                    f_dbg.write(f"RERUN: Edited str_pos={str_pos}, pos={pos}, extracted tracker_id={tracker_id}, changes={changes}\n")

                
                row_data = conn.execute(
                    "SELECT status, notes, follow_up_date, resolved, override, override_reason, payment_date, client_name, payer, first_dos, last_dos FROM unskilled_remit_tracker WHERE id = ?",
                    [tracker_id]
                ).fetchone()
                if not row_data:
                    continue
                cur_status, cur_notes, cur_follow_up, cur_resolved, cur_override, cur_override_reason, cur_pay_date, c_name, c_payer, c_fdos, c_ldos = row_data
                
                new_status = changes.get("status", cur_status)
                new_notes = changes.get("notes", cur_notes)
                new_follow_up = changes.get("follow_up_date", cur_follow_up)
                new_resolved = changes.get("resolved", bool(cur_resolved))
                new_override = changes.get("override", bool(cur_override))
                new_override_reason = changes.get("override_reason", cur_override_reason)
                
                # Auto-align resolved flag and status
                if "resolved" in changes:
                    if changes["resolved"]:
                        new_status = "RESOLVED"
                    else:
                        new_status = "PENDING" if new_status == "RESOLVED" else new_status
                if "status" in changes:
                    if changes["status"] == "RESOLVED":
                        new_resolved = True
                    else:
                        new_resolved = False if new_status != "RESOLVED" else new_resolved
                        
                payment_date_val = cur_pay_date
                if new_resolved and not payment_date_val:
                    payment_date_val = date.today()
                elif not new_resolved:
                    payment_date_val = None
                    
                # Audit fields for override
                overridden_by = None
                override_date_val = None
                if new_override:
                    overridden_by = st.session_state.get("active_analyst", "MA")
                    row_audit = conn.execute("SELECT overridden_by, override_date FROM unskilled_remit_tracker WHERE id = ?", [tracker_id]).fetchone()
                    if row_audit and row_audit[0]:
                        overridden_by = row_audit[0]
                        override_date_val = row_audit[1]
                    else:
                        override_date_val = date.today()
                else:
                    overridden_by = None
                    override_date_val = None
                
                # Guard NaT/empty dates
                if new_follow_up == "":
                    new_follow_up = None
                elif pd.isna(new_follow_up):
                    new_follow_up = None
                elif isinstance(new_follow_up, str):
                    try:
                        new_follow_up = pd.to_datetime(new_follow_up).date()
                    except Exception:
                        new_follow_up = None

                conn.execute("""
                    UPDATE unskilled_remit_tracker
                    SET status = ?,
                        notes = ?,
                        follow_up_date = ?,
                        resolved = ?,
                        override = ?,
                        override_reason = ?,
                        overridden_by = ?,
                        override_date = ?,
                        payment_date = ?
                    WHERE id = ?
                """, [
                    new_status, new_notes, new_follow_up, new_resolved,
                    new_override, new_override_reason, overridden_by, override_date_val,
                    payment_date_val, tracker_id
                ])
                
                # Back-propagate to reconciliation table so Dashboards and Ledgers see it
                if new_override:
                    reason_to_save = new_override_reason if new_override_reason else "Override"
                    conn.execute("""
                        UPDATE reconciliation
                        SET analyst_override = ?
                        WHERE client_name_payroll = ?
                          AND insurance = ?
                          AND week_start_date = ?
                          AND week_end_date = ?
                          AND care_type = 'Unskilled'
                    """, [reason_to_save, c_name, c_payer, c_fdos, c_ldos])
                elif not new_override and cur_override:
                    # Clear override if unchecked
                    conn.execute("""
                        UPDATE reconciliation
                        SET analyst_override = NULL
                        WHERE client_name_payroll = ?
                          AND insurance = ?
                          AND week_start_date = ?
                          AND week_end_date = ?
                          AND care_type = 'Unskilled'
                    """, [c_name, c_payer, c_fdos, c_ldos])
                    
            conn.commit()
            st.success("Edits saved successfully!")
            del st.session_state[state_key]
            st.rerun()

    st.caption(f"Showing {len(df)} tracker entries. Double-click cells to edit inline, then click outside the table or press Enter to apply.")

    # Apply CSS color styling to rows
    def style_row(row):
        if row.get("override") or "Override" in row.get("status_badge", ""):
            return ["background-color: #1e1b4b; color: #a5b4fc;"] * len(row)
        elif "Resolved" in row.get("status_badge", ""):
            return ["background-color: #064e3b; color: #6ee7b7;"] * len(row)
        elif "🔴 Escalated" in row.get("status_badge", ""):
            return ["background-color: #4c0519; color: #fda4af;"] * len(row)
        return [""] * len(row)

    styled_df = df_display.style.apply(style_row, axis=1)

    # Save ID mapping for robust positional lookup on rerun
    st.session_state["unskilled_tracker_ids"] = df["id"].tolist()

    # Render data editor
    st.data_editor(
        styled_df,
        key=state_key,
        use_container_width=True,
        hide_index=True,
        disabled=[
            "status_badge", "client_name", "payer", "first_dos", "last_dos",
            "regular_hours", "respite_hours", "pending_hours"
        ],
        column_config={
            "status_badge": st.column_config.TextColumn("Badge", disabled=True, width="small"),
            "client_name": st.column_config.TextColumn("Client", disabled=True),
            "payer": st.column_config.TextColumn("Payer", disabled=True, width="small"),
            "first_dos": st.column_config.DateColumn("First DOS", disabled=True, format="YYYY-MM-DD", width="small"),
            "last_dos": st.column_config.DateColumn("Last DOS", disabled=True, format="YYYY-MM-DD", width="small"),
            "regular_hours": st.column_config.NumberColumn("Reg Hrs", format="%.1f", disabled=True, width="small"),
            "respite_hours": st.column_config.NumberColumn("Resp Hrs", format="%.1f", disabled=True, width="small"),
            "pending_hours": st.column_config.NumberColumn("Pending Hrs", format="%.1f", disabled=True, width="small"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
            "override_reason": st.column_config.SelectboxColumn("Close Reason", options=["", "Paid", "Lost Money", "Write Off", "Duplicate", "Other"], width="medium"),
            "override": st.column_config.CheckboxColumn("Close Claim", width="small"),
            "follow_up_date": st.column_config.DateColumn("Follow-Up Date", format="YYYY-MM-DD", width="small")
        }
    )
else:
    st.info("No items match the current filters.")
