import streamlit as st
import pandas as pd

import db
import auth

auth.require_login()

st.title("🗂️ Audit Log")

entries = db.list_audit_log()
if not entries:
    st.info("No activity recorded yet.")
else:
    df = pd.DataFrame(entries)
    df.columns = ["User", "Action", "Details", "Timestamp"]
    st.dataframe(df, use_container_width=True, hide_index=True)
