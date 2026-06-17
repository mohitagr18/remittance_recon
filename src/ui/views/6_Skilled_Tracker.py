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
import plotly.graph_objects as go

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import cfg
from src.ui.components.filters import _get_conn
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
# Lower number = higher priority (shown first)
STATUS_SORT = {
    "Unpaid":       0,
    "Partial":      1,
    "Paid in Full": 2,
    "No Claims":    3,
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
def _render_comments(conn, display_name: str, bill_code: str, billing_week: str, sel_key: str):
    """Post-only form. Comments are displayed inline in the table."""
    key_prefix  = f"cmt_{display_name}_{bill_code}_{billing_week}".replace(" ", "_").replace("/", "_").replace("'", "")
    reset_flag  = f"reset_{sel_key}"
    st.markdown(f"**💬 Add comment — {display_name} ({bill_code}) · {billing_week}**")
    with st.form(key=f"form_{key_prefix}"):
        col1, col2 = st.columns([3, 1])
        new_comment = col1.text_area("Comment", key=f"txt_{key_prefix}",
                                     label_visibility="collapsed", placeholder="Type your comment…", height=68)
        author = col2.text_input("Your name", key=f"auth_{key_prefix}",
                                 label_visibility="collapsed", placeholder="Your name")
        if st.form_submit_button("Post", use_container_width=True):
            if new_comment.strip() and author.strip():
                Q.add_tracker_comment(conn, display_name, bill_code, billing_week,
                                      new_comment.strip(), author.strip())
                st.session_state[reset_flag] = True
                st.rerun()
            else:
                st.warning("Both comment and your name are required.")


# ── Weekly table ───────────────────────────────────────────────────────────────
def _render_week(conn, ws: date, we: date, month_idx: int = 0):
    week_label = _fmt_week(ws, we)
    df = Q.get_tracker_week_data(conn, str(ws), str(we))

    if df.empty:
        st.info("No data for this week.")
        return

    # ── Status filter ──────────────────────────────────────────────────────────
    all_statuses = list(STATUS_SORT.keys())
    filter_key = f"status_filter_{month_idx}_{ws}_{we}"
    selected_statuses = st.multiselect(
        "Filter by status:",
        options=all_statuses,
        default=[],
        key=filter_key,
        placeholder="All statuses shown",
    )
    if selected_statuses:
        df = df[df["status"].isin(selected_statuses)].copy()

    if df.empty:
        st.info("No rows match the selected filter.")
        return

    # ── Sort by status priority ────────────────────────────────────────────────
    df = df.copy()
    df["_sort"] = df["status"].map(STATUS_SORT).fillna(99)
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

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

    # Build Comments column: full text list per row
    def _comment_text(row):
        cdf = Q.get_tracker_comments(conn, row["display_name"], row["bill_code"], week_label)
        if cdf.empty:
            return ""
        lines = []
        for _, c in cdf.iterrows():
            ts = pd.to_datetime(c["created_at"]).strftime("%-m/%-d %-I:%M %p")
            lines.append(f"{c['author']} [{ts}]: {c['comment_text']}")
        return "\n".join(lines)

    display_df["Comments"] = df.apply(_comment_text, axis=1)

    # Totals row (always from full unfiltered df for accurate totals)
    full_df = Q.get_tracker_week_data(conn, str(ws), str(we))
    totals = {
        "Client": "TOTAL", "Bill Code": "", "Payroll Hrs": round(full_df["payroll_hrs"].sum(), 2),
        "Units Billed": round(full_df["units_billed"].sum(), 2),
        "Billed $": _fmt_usd(full_df["billed_amt"].sum()),
        "Paid $":   _fmt_usd(full_df["paid_amt"].sum()),
        "Pending $":_fmt_usd(full_df["pending_amt"].sum()),
        "Status": "", "Comments": "",
    }
    display_df = pd.concat([display_df, pd.DataFrame([totals])], ignore_index=True)

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Comments": st.column_config.TextColumn("💬 Comments", width="large"),
        }
    )

    # Row selector for comments — resets to "— select —" after posting
    sel_key = f"sel_{month_idx}_{ws}_{we}"
    reset_flag = f"reset_{sel_key}"
    # If a comment was just posted, clear the flag and reset the index before widget renders
    if st.session_state.get(reset_flag):
        del st.session_state[reset_flag]
        if sel_key in st.session_state:
            del st.session_state[sel_key]
    client_options = df["display_name"] + " (" + df["bill_code"] + ")"
    selected = st.selectbox("Add comment for:", ["— select a client —"] + list(client_options),
                            key=sel_key)
    if selected and selected != "— select a client —":
        idx = list(client_options).index(selected)
        row = df.iloc[idx]
        _render_comments(conn, row["display_name"], row["bill_code"], week_label, sel_key=sel_key)

    # Add new client row
    with st.expander("➕ Add Client Row"):
        with st.form(key=f"add_client_{month_idx}_{ws}_{we}"):
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



# ── Heatmap chart ──────────────────────────────────────────────────────────────
def _build_heatmap(df) -> go.Figure:
    """Build client × month collection-rate heatmap from get_tracker_heatmap() output."""
    month_keys = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]
    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    # Only include months up to today
    from datetime import date as _date
    cur_month = _date.today().month
    month_keys   = month_keys[:cur_month]
    month_labels = month_labels[:cur_month]

    clients = df["client_label"].tolist()
    z, text = [], []
    for _, row in df.iterrows():
        row_z, row_t = [], []
        for mk in month_keys:
            b = row.get(f"{mk}_b", 0) or 0
            p = row.get(f"{mk}_p", 0) or 0
            if b == 0:
                row_z.append(None)
                row_t.append("—")
            else:
                rate = min(p / b * 100, 100)
                row_z.append(rate)
                row_t.append(f"{rate:.0f}%<br>${p:,.0f} / ${b:,.0f}")
        z.append(row_z)
        text.append(row_t)

    fig = go.Figure(go.Heatmap(
        z=z,
        x=month_labels,
        y=clients,
        text=text,
        texttemplate="%{text}",
        hovertemplate="<b>%{y}</b><br>%{x}: %{text}<extra></extra>",
        colorscale=[
            [0.0,  "#a12c7b"],   # Red  — 0%
            [0.5,  "#d19900"],   # Gold — 50%
            [0.75, "#edb336"],   # Yellow — 75%
            [0.95, "#437a22"],   # Green — 95%
            [1.0,  "#01696f"],   # Teal — 100%
        ],
        zmin=0, zmax=100,
        colorbar=dict(
            title=dict(text="Collection %", font=dict(color="#cdccca")),
            ticksuffix="%",
            tickfont=dict(color="#cdccca"),
        ),
        xgap=2, ygap=2,
    ))

    fig.update_layout(
        title=dict(text="Collection Rate by Client × Month", font=dict(color="#cdccca", size=15)),
        paper_bgcolor="#1c1b19",
        plot_bgcolor="#1c1b19",
        font=dict(color="#cdccca", size=11),
        height=max(300, len(clients) * 38 + 80),
        margin=dict(l=10, r=10, t=50, b=40),
        xaxis=dict(side="top", tickfont=dict(color="#cdccca")),
        yaxis=dict(tickfont=dict(color="#cdccca"), autorange="reversed"),
    )
    return fig

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

    # ── Heatmap ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Collection Rate by Client × Month")
    heatmap_df = Q.get_tracker_heatmap(conn, YEAR)
    if not heatmap_df.empty:
        st.plotly_chart(_build_heatmap(heatmap_df), use_container_width=True)
    else:
        st.info("No remittance data yet to build heatmap.")

    # ── YTD Table ─────────────────────────────────────────────────────────────
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
    conn = _get_conn()

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
                    _render_week(conn, ws, we, month_idx=i)


main()
