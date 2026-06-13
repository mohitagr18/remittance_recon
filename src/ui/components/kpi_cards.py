"""
src/ui/components/kpi_cards.py
Reusable KPI card HTML components.
"""
from __future__ import annotations
import streamlit as st


_COLORS = ["blue", "green", "yellow", "red", "purple"]


def kpi_card(label: str, value: str, sub: str = "", color: str = "blue") -> str:
    return f"""
    <div class="kpi-card {color}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {"<div class='kpi-sub'>" + sub + "</div>" if sub else ""}
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
