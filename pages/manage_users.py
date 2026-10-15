import streamlit as st

import db
import auth

auth.require_login()
user = auth.current_user()

st.title("👥 Manage Users")

st.subheader("Existing HR Officer accounts")
users = db.list_users()
for u in users:
    cols = st.columns([3, 2, 1.5, 1.5])
    cols[0].write(f"**{u['full_name']}**  \n@{u['username']}")
    cols[1].write(u["created_at"])
    cols[2].write("Active" if u["is_active"] else "Inactive")
    if u["id"] != user["id"]:
        label = "Deactivate" if u["is_active"] else "Reactivate"
        if cols[3].button(label, key=f"toggle_{u['id']}"):
            db.set_user_active(u["id"], not u["is_active"])
            db.log_action(user["id"], user["username"], "user_status_change", f'{u["username"]} -> {not u["is_active"]}')
            st.rerun()

st.divider()
st.subheader("Add a new HR Officer account")
with st.form("add_user_form", clear_on_submit=True):
    full_name = st.text_input("Full name")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    submitted = st.form_submit_button("Create account")

if submitted:
    if not full_name or not username or not password:
        st.error("All fields are required.")
    elif db.get_user_by_username(username):
        st.error("That username is already taken.")
    else:
        db.create_user(username, auth.hash_password(password), full_name, role="admin")
        db.log_action(user["id"], user["username"], "user_created", username)
        st.success(f"Account for {full_name} created.")
        st.rerun()
