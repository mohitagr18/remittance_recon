"""
src/ui/components/charts.py
Plotly chart builders for the UI.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.ui.styles.theme import COLORS, PLOTLY_TEMPLATE, PAYER_PALETTE

_LAYOUT_DEFAULTS = dict(
    paper_bgcolor="#1e2130",
    plot_bgcolor="#1e2130",
    font=dict(family="Inter", color="#e8eaf0", size=12),
    margin=dict(l=12, r=12, t=36, b=12),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color="#c8cfe0", size=11),
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
)


def rolling_trend_chart(df: pd.DataFrame) -> go.Figure:
    """Grouped bar chart — Billed vs Paid vs Pending hours by week."""
    if df.empty:
        return _empty_fig("No trend data available")

    df = df.copy()
    df["week"] = pd.to_datetime(df["week_start_date"]).dt.strftime("%b %d")

    fig = go.Figure()
    fig.add_bar(
        name="Billed",
        x=df["week"],
        y=df["billed_hrs"],
        marker_color="#4f8ef7",
        marker_line_width=0,
    )
    fig.add_bar(
        name="Paid",
        x=df["week"],
        y=df["paid_hrs"],
        marker_color="#22c55e",
        marker_line_width=0,
    )
    fig.add_bar(
        name="Pending",
        x=df["week"],
        y=df["pending_hrs"],
        marker_color="#f59e0b",
        marker_line_width=0,
    )
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        barmode="group",
        bargap=0.18,
        bargroupgap=0.06,
        xaxis=dict(gridcolor="#2a2d3e", tickfont=dict(size=11, color="#c8cfe0"), linecolor="#2a2d3e"),
        yaxis=dict(gridcolor="#2a2d3e", title="Hours", tickfont=dict(color="#c8cfe0"), linecolor="#2a2d3e"),
        height=280,
    )
    return fig


def followup_donut(df: pd.DataFrame) -> go.Figure:
    """Donut chart for follow-up reason breakdown."""
    if df.empty:
        return _empty_fig("No follow-up data")

    colors = ["#4f8ef7", "#ef4444", "#f59e0b", "#a78bfa", "#22c55e", "#06b6d4", "#f97316"]
    fig = go.Figure(
        go.Pie(
            labels=df["reason"],
            values=df["count"],
            hole=0.62,
            marker=dict(colors=colors, line=dict(width=2, color="#0f1117")),
            textinfo="percent",
            textfont=dict(size=11),
            hovertemplate="<b>%{label}</b><br>Count: %{value}<br>%{percent}<extra></extra>",
        )
    )
    _donut_layout = {k: v for k, v in _LAYOUT_DEFAULTS.items() if k not in ("legend", "margin")}
    fig.update_layout(
        **_donut_layout,
        height=280,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            font=dict(size=10),
        ),
        margin=dict(l=0, r=120, t=16, b=0),
    )
    return fig


def payer_bar_chart(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart of payer collection rates, color-coded vs 95% target."""
    if df.empty:
        return _empty_fig("No payer data")

    df = df.copy().sort_values("collection_rate_pct", ascending=True)

    colors = []
    for rate in df["collection_rate_pct"]:
        if rate is None or pd.isna(rate):
            colors.append("#3a3d4e")
        elif rate >= 95:
            colors.append("#22c55e")
        elif rate >= 85:
            colors.append("#f59e0b")
        else:
            colors.append("#ef4444")

    fig = go.Figure(
        go.Bar(
            x=df["collection_rate_pct"],
            y=df["insurance"],
            orientation="h",
            marker_color=colors,
            marker_line_width=0,
            text=[f"{r:.1f}%" if r and not pd.isna(r) else "N/A" for r in df["collection_rate_pct"]],
            textposition="outside",
            textfont=dict(size=11),
            hovertemplate="<b>%{y}</b><br>Collection Rate: %{x:.1f}%<extra></extra>",
        )
    )
    fig.add_vline(
        x=95,
        line_dash="dash",
        line_color="#4f8ef7",
        line_width=1.5,
        annotation_text="95% target",
        annotation_font_size=10,
        annotation_font_color="#4f8ef7",
    )
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        xaxis=dict(range=[0, 115], gridcolor="#2a2d3e", ticksuffix="%", tickfont=dict(color="#c8cfe0"), linecolor="#2a2d3e"),
        yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color="#e8eaf0", size=12)),
        height=max(180, len(df) * 42),
        showlegend=False,
    )
    return fig


def client_billed_paid_chart(df: pd.DataFrame) -> go.Figure:
    """Weekly billed vs paid bar chart for a specific client."""
    if df.empty:
        return _empty_fig("No payment history")

    df = df.copy()
    df["week"] = pd.to_datetime(df["week_start_date"]).dt.strftime("%b %d")

    fig = go.Figure()
    fig.add_bar(name="Billed", x=df["week"], y=df["billed_hours"], marker_color="#4f8ef7")
    fig.add_bar(name="Paid", x=df["week"], y=df["paid_hours"], marker_color="#22c55e")
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        barmode="group",
        height=240,
        xaxis=dict(gridcolor="#2a2d3e", tickfont=dict(color="#c8cfe0"), linecolor="#2a2d3e"),
        yaxis=dict(gridcolor="#2a2d3e", title="Hours", tickfont=dict(color="#c8cfe0"), linecolor="#2a2d3e"),
    )
    return fig


def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=14, color="#8892a4"),
    )
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        height=220,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig
