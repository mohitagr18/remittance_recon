"""
src/ui/views/8_Unskilled_Remittance_Tracker.py
Unskilled Remittance Tracker — Analyst view + Executive dashboard.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.config import cfg
from src.db.connection import get_conn
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
def _conn():
    return get_conn(cfg.db_path)


conn = _conn()


# ══════════════════════════════════════════════════════════════════════════════
# SYNC HELPER (runs on every page load)
# ══════════════════════════════════════════════════════════════════════════════

def _run_sync() -> None:
    """Sync new pending rows + update payments + refresh escalation flags."""
    sync_pending_from_reconciliation(conn)
    sync_payments_from_remittance(conn)
    refresh_escalation_flags(conn)


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

pending_df = get_pending_df(conn)
escalated_df = pending_df[pending_df["is_escalated"] == True]

# ── Escalation banner ─────────────────────────────────────────────────────────
if not escalated_df.empty:
    with st.expander(
        f"🔴 ESCALATION ALERT — {len(escalated_df)} item(s) require immediate attention",
        expanded=True,
    ):
        st.dataframe(
            escalated_df[[
                "client_name", "payer", "first_dos", "last_dos",
                "pending_hours", "escalation_reason", "entry_date",
            ]].rename(columns={
                "client_name": "Client",
                "payer": "Payer",
                "first_dos": "First DOS",
                "last_dos": "Last DOS",
                "pending_hours": "Pending Hrs",
                "escalation_reason": "Reason",
                "entry_date": "Entry Date",
            }),
            use_container_width=True,
            hide_index=True,
        )

# ── Filters ───────────────────────────────────────────────────────────────────
with st.container():
    f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
    search   = f1.text_input("🔍 Search client", placeholder="Type client name…")
    payers   = ["All"] + sorted(pending_df["payer"].dropna().unique().tolist())
    payer_f  = f2.selectbox("Payer", payers)
    statuses = ["All", "PENDING", "PARTIAL", "ESCALATED"]
    status_f = f3.selectbox("Status", statuses)
    dos_range = f4.date_input("DOS range", value=[], help="Filter by First DOS")

# Apply filters
df = pending_df.copy()
if search:
    df = df[df["client_name"].str.contains(search, case=False, na=False)]
if payer_f != "All":
    df = df[df["payer"] == payer_f]
if status_f != "All":
    df = df[df["status"] == status_f]
if isinstance(dos_range, (list, tuple)) and len(dos_range) == 2:
    df = df[(df["first_dos"] >= str(dos_range[0])) & (df["first_dos"] <= str(dos_range[1]))]

st.caption(f"Showing {len(df)} of {len(pending_df)} pending items")

# ── Main pending grid ─────────────────────────────────────────────────────────
if df.empty:
    st.info("No items match the current filters.")
else:
    for _, row in df.iterrows():
        tracker_id = int(row["id"])
        status_icon, bg = _BADGE.get(row["status"], ("⚪", "#eee"))
        escalation_tag = " 🔴" if row["is_escalated"] else ""

        label = (
            f"{status_icon} "
            f"**[{row['client_name']}](1_Client_Ledger)**"
            f"{escalation_tag}  |  "
            f"{row['payer']}  |  "
            f"DOS: {row['first_dos']} – {row['last_dos']}  |  "
            f"Pending: **{row['pending_hours']:.1f} hrs**  |  "
            f"💬 {int(row['comment_count'])}"
        )

        with st.expander(label, expanded=False):
            # ── Read-only fields (system-owned) ───────────────────────────────
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown("**System Info** *(read-only)*")
                st.write(f"- **Entry Date:** {row['entry_date']}")
                st.write(f"- **Payer:** {row['payer']}")
                st.write(f"- **Regular Hours (payroll):** {row['regular_hours']:.1f}")
                st.write(f"- **Respite Hours (payroll):** {row['respite_hours']:.1f}")
                st.write(f"- **Pending Hours:** {row['pending_hours']:.1f}")
                st.write(f"- **Status:** {_badge(row['status'])}")
                if row["is_escalated"]:
                    st.warning(f"Escalated — {row['escalation_reason']}")

            with col_r:
                st.markdown(
                    f"🔗 [Open Client Ledger](1_Client_Ledger) *(opens in new tab)*",
                    unsafe_allow_html=False,
                )

            st.divider()

            # ── Rebill attempts (analyst editable) ────────────────────────────
            st.markdown("**Rebill Attempts**")
            rb1, rb2, rb3 = st.columns(3)

            with rb1:
                st.caption("1st Attempt")
                r1_date  = st.date_input("Date##1",  value=row["rebill1_date"]  or None, key=f"r1d_{tracker_id}")
                r1_hours = st.number_input("Hours##1", value=float(row["rebill1_hours"] or 0), min_value=0.0, step=0.5, key=f"r1h_{tracker_id}")
                if st.button("Save", key=f"save1_{tracker_id}"):
                    save_rebill_attempt(conn, tracker_id, 1, r1_date, r1_hours)
                    st.success("Saved 1st attempt.")
                    st.rerun()

            with rb2:
                st.caption("2nd Attempt")
                r2_date  = st.date_input("Date##2",  value=row["rebill2_date"]  or None, key=f"r2d_{tracker_id}")
                r2_hours = st.number_input("Hours##2", value=float(row["rebill2_hours"] or 0), min_value=0.0, step=0.5, key=f"r2h_{tracker_id}")
                if st.button("Save", key=f"save2_{tracker_id}"):
                    save_rebill_attempt(conn, tracker_id, 2, r2_date, r2_hours)
                    st.success("Saved 2nd attempt.")
                    st.rerun()

            with rb3:
                st.caption("3rd Attempt")
                r3_date  = st.date_input("Date##3",  value=row["rebill3_date"]  or None, key=f"r3d_{tracker_id}")
                r3_hours = st.number_input("Hours##3", value=float(row["rebill3_hours"] or 0), min_value=0.0, step=0.5, key=f"r3h_{tracker_id}")
                if st.button("Save", key=f"save3_{tracker_id}"):
                    save_rebill_attempt(conn, tracker_id, 3, r3_date, r3_hours)
                    st.success("Saved 3rd attempt.")
                    st.rerun()

            st.divider()

            # ── Comment log ───────────────────────────────────────────────────
            st.markdown("**Comments**")
            comments_df = get_comments(conn, tracker_id)
            if comments_df.empty:
                st.caption("No comments yet.")
            else:
                for _, c in comments_df.iterrows():
                    ts = pd.to_datetime(c["created_at"]).strftime("%m/%d/%y %I:%M %p")
                    st.markdown(f"`{ts}` **{c['author']}** — {c['comment_text']}")

            with st.form(key=f"comment_form_{tracker_id}", clear_on_submit=True):
                author   = st.selectbox("Analyst", ANALYST_OPTIONS, key=f"auth_{tracker_id}")
                new_note = st.text_area("Add comment", key=f"note_{tracker_id}", height=80)
                if st.form_submit_button("Post Comment"):
                    if new_note.strip():
                        add_comment(conn, tracker_id, author, new_note.strip())
                        st.rerun()
                    else:
                        st.warning("Comment cannot be empty.")


# ── Resolved / Paid section ───────────────────────────────────────────────────
with st.expander("✅ Resolved / Paid Items", expanded=False):
    resolved_df = get_resolved_df(conn)
    if resolved_df.empty:
        st.info("No resolved items yet.")
    else:
        for _, row in resolved_df.iterrows():
            rcol1, rcol2 = st.columns([8, 1])
            rcol1.write(
                f"**{row['client_name']}** | {row['payer']} | "
                f"DOS {row['first_dos']} – {row['last_dos']} | "
                f"Paid {row['payment_date']}"
            )
            if rcol2.button("Re-open", key=f"reopen_{row['id']}"):
                reopen_resolved_row(conn, int(row["id"]))
                st.success("Row re-opened and returned to pending.")
                st.rerun()
