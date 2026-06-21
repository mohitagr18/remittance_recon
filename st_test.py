import streamlit as st
import pandas as pd

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"]}, index=[10, 20, 30])

edits = st.data_editor(st.session_state.df, hide_index=True)
st.write(st.session_state.get("edited_rows", {}))
st.write(edits)
