"""
src/ui/views/6_Skilled_Tracker.py
Skilled Billing Tracker — monthly/weekly view built from live DuckDB data.
"""
from __future__ import annotations
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import cfg
from src.db import get_conn
import src.db.queries as Q

# ── constants ─────────────────────────────────────────────────────────────────
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
YEAR = 2026
STATUS_COLORS = {
    "Paid in Full": "🟢",
    "Partial":      "🟡",
    "Unpaid":       "🔴",
    "No Claims":    "⚪",
}


def _weeks_in_month(year: int, month: int) -> list[tuple[date, date]]:
    """Return (week_start, week_end) tuples for billing weeks overlapping the given month."""
    weeks = []
    d = date(year, month, 1)
    # Move to Monday of first week
    d -= timedelta(days=d.weekday())
    while True:
        ws = d
        we = d + timedelta(days=6)
        if ws.month > month and ws.year >= year:
            break
        # Include if any day of the week falls in the target month
        month_start = date(year, month, 1)
        next_month = date(year + (month // 12), (month % 12) + 1, 1)
        if we >= month_start and ws < next_month:
            weeks.append((ws, we))
        d += timedelta(days=7)
        if d.year > year:
            break
    return weeks


def _fmt_week(ws: date, we: date) -> str:
    return f"{ws.strftime('%m/%d/%y')}–{we.strftime('%m/%d/%y')}"


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


# ── Comments panel ─────────────────────────────────────────────────────────────
def _render_comments(conn, display_name: str, bill_code: str, billing_week: str):
    key_prefix = f"cmt_{display_name}_{bill_code}_{billing_week}".replace(" ", "_").replace("/", "_").replace("'", "")
    comments_df = Q.get_tracker_comments(conn, display_name, bill_code, billing_week)

    with st.container():
        st.markdown(f"**💬 Comments — {display_name} ({bill_code}) · {billing_week}**")
        if comments_df.empty:
            st.caption("No comments yet.")
        else:
            for _, row in comments_df.iterrows():
                ts = pd.to_datetime(row["created_at"]).strftime("%b %d, %Y %I:%M %p")
                st.markdown(
                    f"<div style='background:#1e2130;border-radius:8px;padding:8px 12px;margin-bottom:6px;'>"
                    f"<span style='color:#4f98a3;font-weight:600;'>{row['author']}</span>"
                    f"<span style='color:#797876;font-size:0.8em;margin-left:8px;'>{ts}</span><br/>"
                    f"<span style='color:#cdccca;'>{row['comment_text']}</span></div>",
                    unsafe_allow_html=True,
                )

        with st.form(key=f"form_{key_prefix}"):
            col1, col2 = st.columns([3, 1])
            new_comment = col1.text_area("Add a comment", key=f"txt_{key_prefix}", label_visibility="collapsed", placeholder="Add a comment…", height=68)
            author = col2.text_input("Your name", key=f"auth_{key_prefix}", label_visibility="collapsed", placeholder="Your name")
            submitted = st.form_submit_button("Post", use_container_width=True)
            if submitted:
                if new_comment.strip() and author.strip():
                    Q.add_tracker_comment(conn, display_name, bill_code, billing_week, new_comment.strip(), author.strip())
                    st.success("Comment saved.")
                    st.rerun()
                else:
                    st.warning("Both comment text and your name are required.")


# ── Weekly table ───────────────────────────────────────────────────────────────
def _render_week(conn, ws: date, we: date):
    week_label = _fmt_week(ws, we)
    df = Q.get_tracker_week_data(conn, str(ws), str(we))

    if df.empty:
        st.info("No data for this week.")
        return

    # Build display dataframe
    display_cols = ["display_name", "bill_code", "payroll_hrs", "units_billed",
                    "billed_amt", "paid_amt", "pending_amt", "status"]
    display_df = df[display_cols].copy()
    display_df.columns = ["Client", "Bill Code", "Payroll Hrs", "Units Billed",
                          "Billed $", "Paid $", "Pending $", "Status"]

    # Format currency
    for col in ["Billed $", "Paid $", "Pending $"]:
        display_df[col] = display_df[col].apply(_fmt_usd)
    display_df["Status"] = display_df["Status"].map(lambda s: f"{STATUS_COLORS.get(s, '')} {s}")

    # Comment count badge
    def _comment_count(row):
        cdf = Q.get_tracker_comments(conn, row["display_name"], row["bill_code"], week_label)
        return f"💬 {len(cdf)}" if len(cdf) else "💬"

    display_df["Comments"] = df.apply(_comment_count, axis=1)

    # Totals row
    totals = {
        "Client": "**TOTAL**", "Bill Code": "", "Payroll Hrs": round(df["payroll_hrs"].sum(), 2),
        "Units Billed": round(df["units_billed"].sum(), 2),
        "Billed $": _fmt_usd(df["billed_amt"].sum()),
        "Paid $":   _fmt_usd(df["paid_amt"].sum()),
        "Pending $":_fmt_usd(df["pending_amt"].sum()),
        "Status": "", "Comments": "",
    }
    display_df = pd.concat([display_df, pd.DataFrame([totals])], ignore_index=True)

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Row selector for comments
    client_options = df["display_name"] + " (" + df["bill_code"] + ")"
    selected = st.selectbox("View / add comments for:", ["— select a client —"] + list(client_options),
                            key=f"sel_{ws}_{we}")
    if selected and selected != "— select a client —":
        idx = list(client_options).index(selected)
        row = df.iloc[idx]
        _render_comments(conn, row["display_name"], row["bill_code"], week_label)

    # Add new client row
    with st.expander("➕ Add Client Row"):
        with st.form(key=f"add_client_{ws}_{we}"):
            c1, c2, c3 = st.columns(3)
            new_name = c1.text_input("Display Name (e.g. SMITH, JOHN LPN)")
            new_code = c2.text_input("Bill Code (e.g. T1003)")
            new_svc  = c3.selectbox("Service Type", ["LPN", "RN", "Respite", "Other"])
            new_rem  = st.text_input("Remittance Name (as it appears in remittance file, optional)")
            if st.form_submit_button("Add Row"):
                if new_name.strip() and new_code.strip():
                    Q.add_tracker_client(conn, new_name.strip(), new_code.strip(),
                                         new_svc, new_rem.strip() or None)
                    st.success(f"Added {new_name} / {new_code}. Appears in all future weeks.")
                    st.rerun()
                else:
                    st.warning("Display name and bill code are required.")


# ── Summary (YTD) ──────────────────────────────────────────────────────────────
def _render_summary(conn):
    df = Q.get_tracker_ytd(conn, YEAR)
    if df.empty:
        st.info("No data yet for this year.")
        return

    total_billed  = df["total_billed"].sum()
    total_paid    = df["total_paid"].sum()
    total_pending = df["total_pending"].sum()
    coll_rate     = (total_paid / total_billed * 100) if total_billed else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Billed YTD",   _fmt_usd(total_billed))
    k2.metric("Total Paid YTD",     _fmt_usd(total_paid))
    k3.metric("Total Pending YTD",  _fmt_usd(total_pending))
    k4.metric("Collection Rate",    f"{coll_rate:.1f}%")

    st.markdown("---")
    st.subheader("YTD by Client")

    active_months = [m for i, m in enumerate(MONTHS, 1)
                     if df[m.lower() if m.lower() != "dec" else "dec_"].sum() > 0
                     or i <= date.today().month]
    month_cols = [m.lower() if m.lower() != "dec" else "dec_" for m in active_months]

    ytd_display = df[["display_name", "bill_code", "service_type",
                       "total_hrs", "total_billed", "total_paid", "total_pending"] + month_cols].copy()
    ytd_display.columns = (["Client", "Bill Code", "Service", "Total Hrs",
                             "Billed $", "Paid $", "Pending $"] + active_months)
    for col in ["Billed $", "Paid $", "Pending $"]:
        ytd_display[col] = ytd_display[col].apply(_fmt_usd)
    for m in active_months:
        ytd_display[m] = ytd_display[m].apply(_fmt_usd)

    st.dataframe(ytd_display, use_container_width=True, hide_index=True)


# ── Main page ──────────────────────────────────────────────────────────────────
def main():
    st.title("📊 Skilled Billing Tracker")
    conn = get_conn()

    current_month = date.today().month
    available_months = MONTHS[:current_month]  # Jan..current month

    top_tabs = st.tabs(["📈 Summary (YTD)"] + [f"{m} {YEAR}" for m in available_months])

    with top_tabs[0]:
        _render_summary(conn)

    for i, month_name in enumerate(available_months):
        with top_tabs[i + 1]:
            month_num = i + 1
            weeks = _weeks_in_month(YEAR, month_num)
            if not weeks:
                st.info("No billing weeks found for this month.")
                continue

            week_labels = [_fmt_week(ws, we) for ws, we in weeks]
            week_tabs = st.tabs(week_labels)
            for j, (ws, we) in enumerate(weeks):
                with week_tabs[j]:
                    _render_week(conn, ws, we)


main()
