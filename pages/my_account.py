import streamlit as st

import db
import auth

auth.require_login()
user = auth.current_user()

st.title("⚙️ My Account")
st.write(f"**Name:** {user['full_name']}")
st.write(f"**Username:** {user['username']}")

st.divider()
st.subheader("Change password")
with st.form("change_password_form"):
    current = st.text_input("Current password", type="password")
    new = st.text_input("New password", type="password")
    confirm = st.text_input("Confirm new password", type="password")
    submitted = st.form_submit_button("Update password")

if submitted:
    stored = db.get_user_by_username(user["username"])
    if not auth.verify_password(current, stored["password_hash"]):
        st.error("Current password is incorrect.")
    elif new != confirm:
        st.error("New passwords do not match.")
    elif len(new) < 6:
        st.error("New password must be at least 6 characters.")
    else:
        db.update_password(user["id"], auth.hash_password(new))
        db.log_action(user["id"], user["username"], "password_changed")
        st.success("Password updated.")
