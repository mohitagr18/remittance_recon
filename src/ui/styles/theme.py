"""
src/ui/styles/theme.py
Global theme constants and CSS injection for the Streamlit app.
"""

COLORS = {
    "bg_primary":    "#0f1117",
    "bg_secondary":  "#1a1d27",
    "bg_card":       "#1e2130",
    "bg_card_hover": "#252840",
    "accent_blue":   "#4f8ef7",
    "accent_green":  "#22c55e",
    "accent_yellow": "#f59e0b",
    "accent_red":    "#ef4444",
    "accent_purple": "#a78bfa",
    "text_primary":  "#e8eaf0",
    "text_secondary":"#8892a4",
    "border":        "#2a2d3e",
}

PLOTLY_TEMPLATE = "plotly_dark"

PAYER_PALETTE = {
    "UHC":      "#4f8ef7",
    "Anthem":   "#22c55e",
    "Sentara":  "#a78bfa",
    "Aetna":    "#f59e0b",
    "Medicaid": "#06b6d4",
    "Humana":   "#f97316",
    "PDN":      "#ec4899",
}


def inject_css():
    import streamlit as st

    st.markdown(
        """
        <style>
        /* ── Fonts ──────────────────────────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

        /* ── Main background ─────────────────────────────────── */
        .stApp { background-color: #0f1117; }
        .main .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 1400px;
        }

        /* ── Sidebar ─────────────────────────────────────────── */
        section[data-testid="stSidebar"] {
            background: #13151f !important;
            border-right: 1px solid #1e2130;
        }
        /* Nav links — make them bright and readable */
        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"],
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] li {
            color: #c8cfe0 !important;
            font-size: 0.88rem;
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {
            background: #1e2130 !important;
            color: #ffffff !important;
        }
        section[data-testid="stSidebar"] [aria-selected="true"] {
            background: #1e2840 !important;
            color: #4f8ef7 !important;
            font-weight: 600;
        }
        /* Sidebar filter labels */
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] .stSelectbox label,
        section[data-testid="stSidebar"] .stMultiselect label,
        section[data-testid="stSidebar"] .stToggle label {
            color: #8892a4 !important;
            font-size: 0.75rem !important;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 600 !important;
        }

        /* ── Page headings & body text ───────────────────────── */
        h1, h2, h3, h4 { color: #e8eaf0 !important; }
        p, li, span, div { color: #c8cfe0; }
        .stMarkdown p { color: #c8cfe0; }

        /* ── Section headers ─────────────────────────────────── */
        .section-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 1.5rem 0 0.8rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #2a2d3e;
        }
        .section-header h3 {
            margin: 0;
            font-size: 1rem;
            font-weight: 600;
            color: #e8eaf0 !important;
        }

        /* ── KPI Cards ───────────────────────────────────────── */
        .kpi-card {
            background: linear-gradient(135deg, #1e2130 0%, #252840 100%);
            border: 1px solid #2a2d3e;
            border-radius: 12px;
            padding: 24px 24px 22px;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .kpi-card:hover {
            transform: translateY(-2px);
            border-color: #4f8ef7;
        }
        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            border-radius: 12px 12px 0 0;
        }
        .kpi-card.blue::before   { background: #4f8ef7; }
        .kpi-card.green::before  { background: #22c55e; }
        .kpi-card.yellow::before { background: #f59e0b; }
        .kpi-card.red::before    { background: #ef4444; }
        .kpi-card.purple::before { background: #a78bfa; }
 
        .kpi-label {
            font-size: 0.8rem;
            color: #8892a4;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .kpi-value {
            font-size: 2.2rem;
            font-weight: 700;
            color: #e8eaf0;
            line-height: 1;
            margin-bottom: 4px;
        }
        .kpi-sub { font-size: 0.76rem; color: #8892a4; }

        /* ── Tabs ─────────────────────────────────────────────── */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            background: transparent;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 6px;
            padding: 6px 16px;
            background: #1e2130;
            color: #8892a4 !important;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .stTabs [aria-selected="true"] {
            background: #4f8ef7 !important;
            color: #fff !important;
        }

        /* ── Info/warning banners ────────────────────────────── */
        .info-banner {
            background: #1a2744;
            border: 1px solid #2a4a8a;
            border-radius: 8px;
            padding: 10px 16px;
            font-size: 0.82rem;
            color: #93b4f0;
            margin-bottom: 1rem;
        }

        /* ── Dataframe ───────────────────────────────────────── */
        .stDataFrame { border-radius: 10px; overflow: hidden; }

        /* ── st.info / st.success boxes ─────────────────────── */
        [data-testid="stAlert"] { border-radius: 8px; }

        /* ── Inputs & selects ────────────────────────────────── */
        .stTextInput input,
        .stSelectbox select,
        [data-baseweb="select"] {
            background: #1e2130 !important;
            color: #e8eaf0 !important;
            border-color: #2a2d3e !important;
        }

        /* ── Form submit button ──────────────────────────────── */
        .stFormSubmitButton button {
            background: #4f8ef7 !important;
            color: #fff !important;
            border: none !important;
            border-radius: 6px;
        }

        /* ── Scrollable Plotly Containers ────────────────────── */
        div[data-testid="stPlotlyChart"] {
            overflow-x: auto !important;
            overflow-y: hidden !important;
        }
        div[data-testid="stPlotlyChart"] > div {
            min-width: fit-content !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
