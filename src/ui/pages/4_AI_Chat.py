"""
src/ui/pages/4_AI_Chat.py
AI Chat layer — natural language query interface over the reconciliation database.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

st.set_page_config(page_title="AI Chat", page_icon="🤖", layout="wide")

from src.ui.styles.theme import inject_css
from src.ui.components.filters import _get_conn
from src.config import cfg

inject_css()

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='margin-bottom:1.2rem;'>
        <h1 style='margin:0;font-size:1.5rem;font-weight:700;color:#e8eaf0;'>🤖 AI Chat</h1>
        <div style='font-size:0.82rem;color:#8892a4;margin-top:4px;'>
            Ask questions in plain English — powered by GPT-4o / Gemini
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Check for API key ───────────────────────────────────────────────────────
provider = cfg.llm_provider.lower()
has_key = (provider == "openai" and bool(cfg.openai_api_key)) or \
          (provider == "gemini" and bool(cfg.google_api_key))

if not has_key:
    st.warning(
        f"⚠️ No API key found for **{provider.upper()}**. "
        f"Set `{'OPENAI_API_KEY' if provider == 'openai' else 'GOOGLE_API_KEY'}` in your `.env` file.",
        icon="⚠️",
    )
    st.markdown(
        """
        **To enable AI Chat:**
        1. Open `.env` in the project root
        2. Set `LLM_PROVIDER=openai` (or `gemini`)
        3. Set the corresponding API key
        4. Restart the app
        """,
    )

# ── Sample questions ────────────────────────────────────────────────────────
SAMPLE_QUESTIONS = [
    "How much did we bill this week?",
    "Which clients have follow-ups for UHC?",
    "What's our collection rate by insurance?",
    "Show me the payment history for Baker, Joselyn",
    "How many claims are in the rebill queue?",
]

st.markdown("**💡 Try a sample question:**")
sample_cols = st.columns(len(SAMPLE_QUESTIONS))
chosen_sample = None
for col, q in zip(sample_cols, SAMPLE_QUESTIONS):
    with col:
        if st.button(q, key=f"sample_{q[:20]}", use_container_width=True):
            chosen_sample = q

# ── Chat history ────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ── Chat input ──────────────────────────────────────────────────────────────
st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
user_input = st.chat_input(
    "Ask anything about reconciliation data…",
    key="ai_chat_input",
    disabled=not has_key,
)

# Trigger from sample button
if chosen_sample:
    user_input = chosen_sample

if user_input and has_key:
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    with st.spinner("Thinking…"):
        from src.ai.chat import ask
        conn = _get_conn()
        result = ask(user_input, conn)

    assistant_msg = {
        "role": "assistant",
        "content": result["answer"],
        "sql": result.get("sql", ""),
        "df": result.get("df"),
        "error": result.get("error"),
    }
    st.session_state.chat_history.append(assistant_msg)

# ── Render history ──────────────────────────────────────────────────────────
for msg in reversed(st.session_state.chat_history):
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
        st.markdown(msg["content"])

        if msg["role"] == "assistant":
            if msg.get("sql"):
                with st.expander("🔍 View generated SQL"):
                    st.code(msg["sql"], language="sql")

            df = msg.get("df")
            if df is not None and not df.empty:
                with st.expander(f"📊 View data ({len(df)} rows)"):
                    st.dataframe(df, use_container_width=True, hide_index=True)

if st.session_state.chat_history:
    if st.button("🗑️ Clear conversation", key="clear_chat"):
        st.session_state.chat_history = []
        st.rerun()
