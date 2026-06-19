"""
src/ui/views/5_Data_Management.py
Import Data — linear upload → ingest → verify workflow.

Step 1: Upload payroll and/or remittance files
Step 2: Review detected files and ingest
Step 3: Run automated tests to verify integrity

EVV Tracker Validation moved to bottom as an advanced/collapsible section.
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
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>📥 Import Data</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Upload payroll and remittance files, ingest them into the database, then verify data integrity.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

conn = _get_conn()

# ── STEP 1: Upload Files ───────────────────────────────────────────────────
st.markdown("### Step 1 — Upload Files")
st.caption("Upload one or both files. They will be saved to the correct input directories automatically.")

col_pay, col_rem = st.columns(2)

with col_pay:
    st.markdown("**📄 Payroll File**")
    st.caption("`input/payroll/` — EmpTimeCardReport .xlsx")
    payroll_upload = st.file_uploader(
        "Upload Payroll File",
        type=["xlsx"],
        key="payroll_upload",
        label_visibility="collapsed",
    )
    if payroll_upload:
        dest = cfg.input_dir / "payroll" / payroll_upload.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(payroll_upload.getbuffer())
        st.success(f"✅ Saved: **{payroll_upload.name}**")

with col_rem:
    st.markdown("**📄 Remittance File**")
    st.caption("`input/master_remit/` — Remittance Report Master .xlsx")
    remit_upload = st.file_uploader(
        "Upload Remittance File",
        type=["xlsx"],
        key="remit_upload",
        label_visibility="collapsed",
    )
    if remit_upload:
        dest = cfg.input_dir / "master_remit" / remit_upload.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(remit_upload.getbuffer())
        st.success(f"✅ Saved: **{remit_upload.name}**")

st.markdown("---")

# ── STEP 2: Review & Ingest ────────────────────────────────────────────────
st.markdown("### Step 2 — Review & Ingest")

# Show post-ingest success banners
if st.session_state.get("ingestion_success"):
    st.success("✅ Ingestion completed successfully! Run the tests below to verify data integrity.")
    st.session_state["ingestion_success"] = False

if st.session_state.get("rebuild_success_msg"):
    st.success(st.session_state["rebuild_success_msg"])
    st.session_state["rebuild_success_msg"] = None

files = scan_input_dir(cfg.input_dir, conn)

if not files:
    st.info("📂 No source Excel files found in `input/payroll/` or `input/master_remit/`. Upload files above to get started.", icon="📂")
else:
    file_list = []
    has_pending = False
    for f in files:
        if f.status == "New":
            status_label = "🆕 New — Ready to Ingest"
            has_pending = True
        elif f.status == "Changed":
            status_label = "🔄 Changed — Needs Re-ingest"
            has_pending = True
        else:
            status_label = "✅ Already Ingested"
        file_list.append({
            "Filename": f.filename,
            "Type": "Payroll" if f.file_type == "payroll" else "Remittance",
            "Status": status_label,
            "SHA-256": f.file_hash[:16] + "…",
        })

    st.dataframe(pd.DataFrame(file_list), use_container_width=True, hide_index=True)

    col_ingest, col_rescan, col_spacer = st.columns([2, 1.5, 4])
    with col_ingest:
        if has_pending:
            if st.button("🚀 Ingest New Files", type="primary", use_container_width=True):
                with st.spinner("Running pipeline and rebuilding reconciliation…"):
                    run_pipeline()
                st.session_state["ingestion_success"] = True
                st.rerun()
        else:
            st.button("✅ All Files Up to Date", disabled=True, use_container_width=True)
    with col_rescan:
        if st.button("🔄 Rescan", type="secondary", use_container_width=True):
            st.rerun()

st.markdown("---")

# ── STEP 3: Verify with Tests ──────────────────────────────────────────────
st.markdown("### Step 3 — Verify Data Integrity")
st.caption("Run all automated tests to confirm the pipeline matched names, built reconciliation rows, and computed results correctly.")

if st.button("🧪 Run Tests Now", type="primary"):
    import subprocess, re

    with st.spinner("Running test suite… (up to 20 seconds)"):
        res = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--tb=short"],
            capture_output=True, text=True,
        )

    lines = res.stdout.splitlines()
    passed_tests, failed_tests, skipped_tests = [], [], []
    pattern = re.compile(r"^([^\s]+)\s+(PASSED|FAILED|SKIPPED|ERROR)(?:\s+\[.*\])?$")

    for line in lines:
        m = pattern.match(line.strip())
        if m:
            test_id, result = m.groups()
            parts = test_id.split("::")
            display = f"{parts[-2]} ➔ {parts[-1]}" if len(parts) >= 2 else test_id
            if result == "PASSED":
                passed_tests.append(display)
            elif result in ("FAILED", "ERROR"):
                failed_tests.append((display, result))
            elif result == "SKIPPED":
                skipped_tests.append(display)

    # Parse failure tracebacks
    failures_detail = {}
    if failed_tests:
        try:
            failures_start = res.stdout.find("============================= FAILURES ==============================")
            if failures_start != -1:
                failures_end = res.stdout.find("=========================== short test summary info ===========================")
                if failures_end == -1:
                    failures_end = len(res.stdout)
                block = res.stdout[failures_start:failures_end]
                sections = re.split(r"_{5,}\s*([^\s_]+)\s*_{5,}", block)
                for i in range(1, len(sections), 2):
                    failures_detail[sections[i]] = sections[i + 1].strip()
        except Exception:
            pass

    if not passed_tests and not failed_tests:
        st.error("❌ Could not parse test output.")
        with st.expander("Show raw output"):
            st.code(res.stdout, language="text")
            if res.stderr:
                st.code(res.stderr, language="text")
    elif not failed_tests:
        st.success(f"✅ All {len(passed_tests)} tests passed!")
        if skipped_tests:
            st.info(f"⏭️ {len(skipped_tests)} tests skipped.")
        with st.expander("📋 View passed tests"):
            for t in passed_tests:
                st.write(f"• {t}")
    else:
        st.error(f"❌ {len(failed_tests)} test(s) failed out of {len(passed_tests) + len(failed_tests)} total.")
        st.markdown("**Failed Tests:**")
        for display, result_type in failed_tests:
            st.markdown(f"🔴 **{display}** ({result_type})")
            clean_key = display.replace(" ➔ ", ".")
            tb = failures_detail.get(clean_key, "")
            if not tb:
                for k, v in failures_detail.items():
                    if clean_key.endswith(k) or k.endswith(clean_key):
                        tb = v
                        break
            if tb:
                st.code(tb, language="text")
            else:
                st.caption("No traceback detail available.")

st.markdown("---")

# ── Advanced: Force Rebuild ────────────────────────────────────────────────
with st.expander("🔁 Force Rebuild Reconciliation"):
    st.caption("Rebuilds the reconciliation table from existing DB data without requiring new files. Use after pipeline logic changes.")
    if st.button("🔁 Rebuild Now", type="secondary"):
        from src.db.connection import get_persistent_conn
        from src.etl.pipeline import rebuild_reconciliation, load_name_match_from_db, load_copay_clients_from_db
        from src.etl.name_match import load_name_match, load_copay_clients
        with st.spinner("Rebuilding reconciliation table…"):
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
        st.session_state["rebuild_success_msg"] = (
            f"Done! {summary.recon_rows} rows rebuilt. "
            f"Good: {summary.result_good}, Follow-up: {summary.result_followup}"
        )
        st.rerun()

# ── Advanced: Ingestion History ────────────────────────────────────────────
with st.expander("📜 View Ingestion History"):
    st.markdown("**Payroll Files**")
    payroll_df = queries.ingested_payroll_files_list(conn)
    if payroll_df.empty:
        st.caption("No payroll files ingested yet.")
    else:
        payroll_df["ingested_at"] = pd.to_datetime(payroll_df["ingested_at"]).dt.strftime("%Y-%m-%d %H:%M")
        payroll_df["week_start"] = pd.to_datetime(payroll_df["week_start"]).dt.strftime("%Y-%m-%d").fillna("—")
        payroll_df["week_end"] = pd.to_datetime(payroll_df["week_end"]).dt.strftime("%Y-%m-%d").fillna("—")
        st.dataframe(payroll_df, use_container_width=True, hide_index=True,
            column_config={
                "filename":    st.column_config.TextColumn("Filename", width="medium"),
                "row_count":   st.column_config.NumberColumn("Rows"),
                "week_start":  st.column_config.TextColumn("Week Start"),
                "week_end":    st.column_config.TextColumn("Week End"),
                "ingested_at": st.column_config.TextColumn("Ingested At"),
                "file_hash":   st.column_config.TextColumn("SHA-256", width="medium"),
            })

    st.markdown("**Remittance Files**")
    remit_df = queries.ingested_remittance_files_list(conn)
    if remit_df.empty:
        st.caption("No remittance files ingested yet.")
    else:
        remit_df["ingested_at"] = pd.to_datetime(remit_df["ingested_at"]).dt.strftime("%Y-%m-%d %H:%M")
        remit_df["min_date"] = pd.to_datetime(remit_df["min_date"]).dt.strftime("%Y-%m-%d").fillna("—")
        remit_df["max_date"] = pd.to_datetime(remit_df["max_date"]).dt.strftime("%Y-%m-%d").fillna("—")
        st.dataframe(remit_df, use_container_width=True, hide_index=True,
            column_config={
                "filename":    st.column_config.TextColumn("Filename", width="medium"),
                "row_count":   st.column_config.NumberColumn("Rows"),
                "min_date":    st.column_config.TextColumn("Min Date"),
                "max_date":    st.column_config.TextColumn("Max Date"),
                "ingested_at": st.column_config.TextColumn("Ingested At"),
                "file_hash":   st.column_config.TextColumn("SHA-256", width="medium"),
            })

# ── Advanced: EVV Tracker Validation ──────────────────────────────────────
import json, io
from datetime import datetime

with st.expander("📋 EVV Tracker Validation"):
    st.caption(
        "Upload the latest EVV billing Excel tracker to validate it against live DuckDB data. "
        "Use this to confirm accuracy before retiring the Excel file permanently."
    )

    evv_upload = st.file_uploader(
        "Upload EVV Billing Log (.xlsx)",
        type=["xlsx"],
        key="evv_tracker_upload",
        label_visibility="collapsed",
    )

    tracker_path = cfg.input_dir / "EVV-2026-Billing-Log-Skilled.xlsx"
    if evv_upload:
        tracker_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tracker_path, "wb") as fh:
            fh.write(evv_upload.getbuffer())
        st.success(f"✅ Uploaded: **{evv_upload.name}**")
        st.session_state["evv_tracker_filename"] = evv_upload.name
        st.session_state["evv_tracker_uploaded_at"] = datetime.now().strftime("%b %d, %Y %I:%M %p")

    if tracker_path.exists():
        fname = st.session_state.get("evv_tracker_filename", tracker_path.name)
        utime = st.session_state.get("evv_tracker_uploaded_at", "previously uploaded")
        st.info(f"📄 Current file: **{fname}** · {utime}")
    else:
        st.warning("No EVV tracker file uploaded yet.")

    if st.button("▶ Run EVV Validation", type="primary", disabled=not tracker_path.exists()):
        import importlib.util as _ilu

        spec = _ilu.spec_from_file_location(
            "test_evv_tracker_validation",
            str(_ROOT / "tests" / "test_evv_tracker_validation.py"),
        )
        test_mod = _ilu.module_from_spec(spec)
        sys.modules["test_evv_tracker_validation"] = test_mod
        spec.loader.exec_module(test_mod)

        with st.spinner("Running EVV validation…"):
            results = test_mod.run_all_tests(tracker_path, conn)

        total  = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed

        if failed == 0:
            st.success(f"✅ All {total} validation tests passed!")
        else:
            st.error(f"⚠️ {failed} of {total} tests found discrepancies.")

        for r in results:
            icon = "✅" if r.passed else "⚠️"
            label = f"{icon} **{r.name}** — {r.total_checks - r.failed_checks}/{r.total_checks} matched"
            if r.error:
                with st.expander(f"❌ **{r.name}** — Error"):
                    st.code(r.error)
            elif not r.passed:
                with st.expander(label):
                    st.dataframe(pd.DataFrame(r.diffs), use_container_width=True, hide_index=True)
            else:
                st.markdown(label)

        report_json = json.dumps([r.to_dict() for r in results], default=str)
        fname = st.session_state.get("evv_tracker_filename", tracker_path.name)
        from src.db import queries as _q
        _q.save_validation_run(conn, fname, total, passed, failed, report_json)

        diff_df = test_mod.results_to_df(results)
        if not diff_df.empty:
            buf = io.StringIO()
            diff_df.to_csv(buf, index=False)
            st.download_button(
                label="⬇️ Download Diff Report (CSV)",
                data=buf.getvalue(),
                file_name=f"evv_validation_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv",
                mime="text/csv",
            )

    st.markdown("**Recent Validation Runs**")
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
