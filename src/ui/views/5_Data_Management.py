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

tab_ingest, tab_tests, tab_evv = st.tabs(["📂 File Ingestion & History", "🧪 Automated Test Suite", "📋 EVV Tracker Validation"])

with tab_ingest:
    # Check session state for success messages from runs
    if st.session_state.get("ingestion_success"):
        st.success("✅ Ingestion successfully completed!", icon="✅")
        st.info("💡 **Recommendation:** We recommend running the **Automated Test Suite** (in the next tab) to verify data integrity and name matching.", icon="💡")
        st.session_state["ingestion_success"] = False

    if st.session_state.get("rebuild_success_msg"):
        st.success(st.session_state["rebuild_success_msg"], icon="✅")
        st.session_state["rebuild_success_msg"] = None

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
                    st.session_state["ingestion_success"] = True
                    st.rerun()
            else:
                st.button("🚀 All Files Up to Date", disabled=True, use_container_width=True)
        with col2:
            if st.button("🔄 Rescan Directories", type="secondary", use_container_width=True):
                st.rerun()
    
    # ── Force Rebuild ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**🔁 Force Rebuild Reconciliation**")
    st.caption("Rebuilds reconciliation from existing DB data without requiring new files. Use this after pipeline logic changes.")
    if st.button("🔁 Rebuild Reconciliation Now", type="secondary"):
        from src.db.connection import get_persistent_conn
        from src.etl.pipeline import rebuild_reconciliation, load_name_match_from_db, load_copay_clients_from_db
        from src.config import cfg
        from src.etl.name_match import load_name_match, load_copay_clients
        with st.spinner("Rebuilding reconciliation table..."):
            rconn = get_persistent_conn(cfg.db_path)
            try:
                if cfg.recon_file.exists():
                    name_mapping = load_name_match(cfg.recon_file)
                    copay_set = load_copay_clients(cfg.recon_file)
                else:
                    name_mapping = load_name_match_from_db(rconn)
                    copay_set = load_copay_clients_from_db(rconn)
                summary = rebuild_reconciliation(rconn, name_mapping, copay_set)
            finally:
                rconn.close()
        st.session_state["rebuild_success_msg"] = f"Done! {summary.recon_rows} rows rebuilt. Good: {summary.result_good}, Follow-up: {summary.result_followup}"
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

with tab_tests:
    # ── Test Suite Runner ──────────────────────────────────────────────────────────
    st.markdown(
        "<div class='section-header'><h3>🧪 Automated Test Suite</h3></div>",
        unsafe_allow_html=True,
    )
    st.caption("Run all system test cases to verify data integrity, pipeline matching, and query correctness after importing new files.")
    
    if st.button("🧪 Run Test Suite Now", type="secondary"):
        import subprocess
        import re
        import sys
        
        with st.spinner("Executing system test cases... (This may take up to 20 seconds)"):
            # Run pytest in verbose mode to list every test case
            res = subprocess.run([sys.executable, "-m", "pytest", "-v", "--tb=short"], capture_output=True, text=True)
            
            # Parse output
            lines = res.stdout.splitlines()
            
            passed_tests = []
            failed_tests = []
            skipped_tests = []
            
            # Regex to capture test identifier and result
            pattern = re.compile(r"^([^\s]+)\s+(PASSED|FAILED|SKIPPED|ERROR)(?:\s+\[.*\])?$")
            
            for line in lines:
                m = pattern.match(line.strip())
                if m:
                    test_id, result = m.groups()
                    parts = test_id.split("::")
                    test_display = f"{parts[-2]} ➔ {parts[-1]}" if len(parts) >= 2 else test_id
                    
                    if result == "PASSED":
                        passed_tests.append(test_display)
                    elif result in ("FAILED", "ERROR"):
                        failed_tests.append((test_display, result))
                    elif result == "SKIPPED":
                        skipped_tests.append(test_display)
                        
            # Parse failure details
            failures_detail = {}
            if failed_tests:
                try:
                    stdout_str = res.stdout
                    failures_start = stdout_str.find("============================= FAILURES ==============================")
                    if failures_start != -1:
                        failures_end = stdout_str.find("=========================== short test summary info ===========================")
                        if failures_end == -1:
                            failures_end = len(stdout_str)
                        failures_block = stdout_str[failures_start:failures_end]
                        
                        failure_sections = re.split(r"_{5,}\s*([^\s_]+)\s*_{5,}", failures_block)
                        for i in range(1, len(failure_sections), 2):
                            name = failure_sections[i]
                            traceback = failure_sections[i+1].strip()
                            failures_detail[name] = traceback
                except Exception:
                    pass
                    
        # Display Results
        if not passed_tests and not failed_tests:
            st.error("❌ Failed to run tests or parse test output.")
            with st.expander("Show Console Output"):
                st.code(res.stdout, language="text")
                if res.stderr:
                    st.code(res.stderr, language="text")
        elif len(failed_tests) == 0:
            st.success(f"✅ All {len(passed_tests)} test cases passed successfully!")
            if skipped_tests:
                st.info(f"⏭️ {len(skipped_tests)} test cases skipped.")
            with st.expander("📋 Show Passed Test List"):
                for t in passed_tests:
                    st.write(f"• {t}")
        else:
            st.error(f"❌ {len(failed_tests)} test cases failed (out of {len(passed_tests) + len(failed_tests)} total).")
            
            st.markdown("#### Failed Test Details:")
            for test_display, result_type in failed_tests:
                st.markdown(f"🔴 **{test_display}** ({result_type})")
                clean_key = test_display.replace(" ➔ ", ".")
                tb = failures_detail.get(clean_key, "")
                if not tb:
                    # Fuzzy match
                    for k, v in failures_detail.items():
                        if clean_key.endswith(k) or k.endswith(clean_key):
                            tb = v
                            break
                if tb:
                    st.code(tb, language="text")
                else:
                    st.caption("No traceback detail found in pytest stdout.")


with tab_evv:
    import json, io
    from datetime import datetime

    st.markdown(
        "<div class=\'section-header\'><h3>📋 EVV Tracker Validation</h3></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Upload the latest Excel tracker file to validate it against live DuckDB data. "
        "Use this to confirm accuracy before retiring the Excel file permanently."
    )

    # ── Upload ──────────────────────────────────────────────────────────────────
    st.markdown("#### Upload Tracker File")
    uploaded = st.file_uploader(
        "Upload EVV Billing Log (.xlsx)",
        type=["xlsx"],
        key="evv_tracker_upload",
        label_visibility="collapsed",
    )

    tracker_path = cfg.input_dir / "EVV-2026-Billing-Log-Skilled.xlsx"
    if uploaded:
        tracker_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tracker_path, "wb") as fh:
            fh.write(uploaded.getbuffer())
        st.success(f"✅ Uploaded: **{uploaded.name}** — saved for validation.")
        st.session_state["evv_tracker_filename"] = uploaded.name
        st.session_state["evv_tracker_uploaded_at"] = datetime.now().strftime("%b %d, %Y %I:%M %p")

    if tracker_path.exists():
        fname = st.session_state.get("evv_tracker_filename", tracker_path.name)
        utime = st.session_state.get("evv_tracker_uploaded_at", "previously uploaded")
        st.info(f"📄 Current file: **{fname}** · {utime}", icon="📄")
    else:
        st.warning("No tracker file uploaded yet. Upload one above to run validation.")

    st.markdown("---")

    # ── Run validation ──────────────────────────────────────────────────────────
    if st.button("▶ Run EVV Tracker Validation", type="primary", disabled=not tracker_path.exists()):
        import importlib, sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

        # Lazy import test module
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "test_evv_tracker_validation",
            str(Path(__file__).resolve().parent.parent.parent.parent / "tests" / "test_evv_tracker_validation.py"),
        )
        test_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test_mod)

        with st.spinner("Running validation suite…"):
            results = test_mod.run_all_tests(tracker_path, conn)

        total   = len(results)
        passed  = sum(1 for r in results if r.passed)
        failed  = total - passed

        if failed == 0:
            st.success(f"✅ All {total} validation tests passed!")
        else:
            st.error(f"⚠️ {failed} of {total} tests found discrepancies.")

        st.markdown("#### Results")
        for r in results:
            icon = "✅" if r.passed else "⚠️"
            label = f"{icon} **{r.name}** — {r.total_checks - r.failed_checks}/{r.total_checks} matched"
            if r.error:
                with st.expander(f"❌ **{r.name}** — Error"):
                    st.code(r.error)
            elif not r.passed:
                with st.expander(label):
                    diff_df = pd.DataFrame(r.diffs)
                    st.dataframe(diff_df, use_container_width=True, hide_index=True)
            else:
                st.markdown(label)

        # Save run to DB
        report_json = json.dumps([r.to_dict() for r in results], default=str)
        fname = st.session_state.get("evv_tracker_filename", tracker_path.name)
        from src.db import queries as _q
        _q.save_validation_run(conn, fname, total, passed, failed, report_json)

        # Download report
        diff_df = test_mod.results_to_df(results)
        if not diff_df.empty:
            csv_buf = io.StringIO()
            diff_df.to_csv(csv_buf, index=False)
            st.download_button(
                label="⬇️ Download Diff Report (CSV)",
                data=csv_buf.getvalue(),
                file_name=f"evv_tracker_validation_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv",
                mime="text/csv",
            )

    st.markdown("---")

    # ── History ─────────────────────────────────────────────────────────────────
    st.markdown("#### Recent Validation Runs")
    from src.db import queries as _q2
    hist = _q2.get_validation_history(conn)
    if hist.empty:
        st.caption("No validation runs yet.")
    else:
        hist["run_at"] = pd.to_datetime(hist["run_at"]).dt.strftime("%b %d, %Y %I:%M %p")
        hist["Result"] = hist.apply(
            lambda r: f"✅ {r.passed_tests}/{r.total_tests} passed"
            if r.failed_tests == 0
            else f"⚠️ {r.failed_tests}/{r.total_tests} failed", axis=1
        )
        st.dataframe(
            hist[["run_at", "excel_filename", "Result"]].rename(
                columns={"run_at": "Run At", "excel_filename": "File"}
            ),
            use_container_width=True, hide_index=True,
        )
