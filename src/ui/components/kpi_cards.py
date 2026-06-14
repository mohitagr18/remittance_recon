"""
src/ui/components/kpi_cards.py
Reusable KPI card HTML components with inline styles to guarantee consistent rendering.
"""
from __future__ import annotations
import streamlit as st


def kpi_card(label: str, value: str, sub: str = "", color: str = "blue") -> str:
    color_map = {
        "blue": "#4f8ef7",
        "green": "#22c55e",
        "yellow": "#f59e0b",
        "red": "#ef4444",
        "purple": "#a78bfa"
    }
    top_color = color_map.get(color, "#4f8ef7")

    return f"""
    <div style="
        background: linear-gradient(135deg, #1e2130 0%, #252840 100%);
        border: 1px solid #2a2d3e;
        border-radius: 12px;
        padding: 20px 22px;
        position: relative;
        overflow: hidden;
        border-top: 3px solid {top_color};
        margin-bottom: 1rem;
        height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        box-sizing: border-box;
    ">
        <div style="
            font-size: 0.8rem;
            color: #8892a4;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 600;
            margin-bottom: 8px;
        ">{label}</div>
        <div style="
            font-size: 2.2rem;
            font-weight: 700;
            color: #e8eaf0;
            line-height: 1;
            margin-bottom: 4px;
        ">{value}</div>
        {f'<div style="font-size: 0.76rem; color: #8892a4;">{sub}</div>' if sub else ''}
    </div>
    """


def render_kpi_row(cards: list[dict]) -> None:
    """
    Render a row of KPI cards.
    cards: list of dicts with keys: label, value, sub (optional), color (optional)
    """
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            st.markdown(
                kpi_card(
                    label=card["label"],
                    value=card["value"],
                    sub=card.get("sub", ""),
                    color=card.get("color", "blue"),
                ),
                unsafe_allow_html=True,
            )
