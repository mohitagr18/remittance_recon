"""
src/ui/app.py
Streamlit entry point — Handles navigation and routing.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Recon Platform",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Define pages
dashboard_page = st.Page("views/Dashboard.py", title="Executive Dashboard", icon="📊", default=True)
weekly_recon_page = st.Page("views/0_Weekly_Recon.py", title="Weekly Reconciliation", icon="📋")
client_ledger_page = st.Page("views/1_Client_Ledger.py", title="Client Ledger", icon="📒")
analyst_workbench_page = st.Page("views/2_Analyst_Workbench.py", title="Analyst Workbench", icon="🔧")
ai_chat_page = st.Page("views/4_AI_Chat.py", title="AI Chat", icon="💬")

name_match_page = st.Page("views/3_Name_Match_Manager.py", title="Name Match Manager", icon="⚙️")
data_management_page = st.Page("views/5_Data_Management.py", title="Data Management", icon="⚙️")

# Create navigation structure
pg = st.navigation({
    "Main": [dashboard_page, weekly_recon_page, client_ledger_page, analyst_workbench_page, ai_chat_page],
    "Admin": [name_match_page, data_management_page]
})

# Run navigation
pg.run()
