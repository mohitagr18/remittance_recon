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

# Create navigation structure (hide default sidebar rendering)
pg = st.navigation({
    "Main": [dashboard_page, weekly_recon_page, client_ledger_page, analyst_workbench_page, ai_chat_page],
    "Admin": [name_match_page, data_management_page]
}, position="hidden")

# 1. Render ReconApp branding & Main section at the top of the sidebar
with st.sidebar:
    st.markdown(
        """
        <div style='padding:8px 0 8px;'>
            <div style='font-size:1.15rem;font-weight:700;color:#e8eaf0;'>💰 ReconApp</div>
            <div style='font-size:0.72rem;color:#8892a4;margin-top:2px;'>Billing Reconciliation Platform</div>
        </div>
        <hr style='border-color:#1e2130;margin:8px 0 16px;'/>
        """,
        unsafe_allow_html=True,
    )
    st.page_link(dashboard_page)
    st.page_link(weekly_recon_page)
    st.page_link(client_ledger_page)
    st.page_link(analyst_workbench_page)
    st.page_link(ai_chat_page)

# 2. Run page (this will execute the page script, rendering its content & sidebar filters)
pg.run()

# 3. Render Admin section at the bottom of the sidebar (below page filters)
with st.sidebar:
    st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("**Admin**")
    st.page_link(name_match_page)
    st.page_link(data_management_page)
