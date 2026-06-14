"""
src/ui/pages/5_Data_Management.py
Data Management Page — incremental ingestion scanner and history logs.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd
import importlib

from src.ui.styles.theme import inject_css
from src.ui.components.filters import _get_conn
from src.db import queries
importlib.reload(queries)
from src.etl.file_watcher import scan_input_dir
from src.etl.pipeline import run_pipeline
from src.config import cfg


inject_css()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>⚙️ Data Management & Ingestion</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Monitor raw source files · trigger incremental loads · view ingestion logs
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()

# ── Scan Directories ───────────────────────────────────────────────────────
st.markdown(
    "<div class='section-header'><h3>🆕 Ingestion Scanner</h3></div>",
    unsafe_allow_html=True,
)

files = scan_input_dir(cfg.input_dir, conn)

if not files:
    st.info("📂 No source Excel files found in directories `input/payroll/` and `input/master_remit/`.", icon="📂")
    if st.button("🔄 Rescan", type="secondary"):
        st.rerun()
else:
    # Build list of dictionaries to render
    file_list = []
    has_pending = False
    for f in files:
        status_label = f.status
        if f.status == "New":
            status_label = "🆕 New File (Pending)"
            has_pending = True
        elif f.status == "Changed":
            status_label = "🔄 Hash Changed (Needs Re-ingest)"
            has_pending = True
        elif f.status == "Ingested":
            status_label = "✅ Already In DB (Skipped)"
            
        file_list.append({
            "Filename": f.filename,
            "Category": "Payroll File" if f.file_type == "payroll" else "Remittance Master",
            "Local Path": str(f.path.relative_to(cfg.input_dir.parent)),
            "Ingestion Status": status_label,
            "File SHA-256": f.file_hash[:16] + "..."
        })
        
    df_files = pd.DataFrame(file_list)
    st.dataframe(df_files, use_container_width=True, hide_index=True)
    
    # ── Action Buttons ─────────────────────────────────────────────────────
    col1, col2, col_spacer = st.columns([2, 1, 4])
    with col1:
        if has_pending:
            if st.button("🚀 Ingest New Files", type="primary", use_container_width=True):
                with st.spinner("Executing pipeline and rebuilding reconciliation..."):
                    summary = run_pipeline()
                st.success("✅ Ingestion successfully completed!", icon="✅")
                st.rerun()
        else:
            st.button("🚀 All Files Up to Date", disabled=True, use_container_width=True)
    with col2:
        if st.button("🔄 Rescan Directories", type="secondary", use_container_width=True):
            st.rerun()

# ── Ingestion History ──────────────────────────────────────────────────────
st.markdown(
    "<div style='margin-top:2rem;' class='section-header'><h3>📜 Payroll Ingestion Logs</h3></div>",
    unsafe_allow_html=True,
)

payroll_df = queries.ingested_payroll_files_list(conn)

if payroll_df.empty:
    st.info("No payroll files have been ingested yet.", icon="ℹ️")
else:
    # Formatting
    payroll_df["ingested_at"] = pd.to_datetime(payroll_df["ingested_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    payroll_df["week_start"] = pd.to_datetime(payroll_df["week_start"]).dt.strftime("%Y-%m-%d").fillna("—")
    payroll_df["week_end"] = pd.to_datetime(payroll_df["week_end"]).dt.strftime("%Y-%m-%d").fillna("—")
    
    st.dataframe(
        payroll_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "filename":     st.column_config.TextColumn("Filename", width="medium"),
            "row_count":    st.column_config.NumberColumn("Row Count"),
            "week_start":   st.column_config.TextColumn("Week Start"),
            "week_end":     st.column_config.TextColumn("Week End"),
            "ingested_at":  st.column_config.TextColumn("Ingested At"),
            "file_hash":    st.column_config.TextColumn("SHA-256 Hash", width="medium")
        }
    )

st.markdown(
    "<div style='margin-top:2rem;' class='section-header'><h3>📜 Remittance Ingestion Logs</h3></div>",
    unsafe_allow_html=True,
)

remit_df = queries.ingested_remittance_files_list(conn)

if remit_df.empty:
    st.info("No remittance files have been ingested yet.", icon="ℹ️")
else:
    # Formatting
    remit_df["ingested_at"] = pd.to_datetime(remit_df["ingested_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    remit_df["min_date"] = pd.to_datetime(remit_df["min_date"]).dt.strftime("%Y-%m-%d").fillna("—")
    remit_df["max_date"] = pd.to_datetime(remit_df["max_date"]).dt.strftime("%Y-%m-%d").fillna("—")
    
    st.dataframe(
        remit_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "filename":     st.column_config.TextColumn("Filename", width="medium"),
            "row_count":    st.column_config.NumberColumn("Row Count"),
            "min_date":     st.column_config.TextColumn("Min Date"),
            "max_date":     st.column_config.TextColumn("Max Date"),
            "ingested_at":  st.column_config.TextColumn("Ingested At"),
            "file_hash":    st.column_config.TextColumn("SHA-256 Hash", width="medium")
        }
    )
