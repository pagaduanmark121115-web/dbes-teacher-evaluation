"""
auth.py — simple username/password auth for HR Officer/Admin users,
backed by Turso via db.py. Only one role exists in this app ('admin' /
displayed as "HR Officer") since only the HR Officer manages activities.
"""

from __future__ import annotations

import bcrypt
import streamlit as st

import db


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def is_logged_in() -> bool:
    return st.session_state.get("user") is not None


def current_user() -> dict | None:
    return st.session_state.get("user")


def login(username: str, password: str) -> bool:
    user = db.get_user_by_username(username)
    if not user or not user["is_active"]:
        return False
    if not verify_password(password, user["password_hash"]):
        return False
    st.session_state["user"] = {"id": user["id"], "username": user["username"], "full_name": user["full_name"], "role": user["role"]}
    db.log_action(user["id"], user["username"], "login")
    return True


def logout():
    user = current_user()
    if user:
        db.log_action(user["id"], user["username"], "logout")
    st.session_state.pop("user", None)


def require_login():
    """Call at the top of every protected page. Renders a login form and stops if not logged in."""
    db.init_db()

    if is_logged_in():
        return

    st.title("DBES Post-Evaluation System")
    st.caption("HR Officer / Admin sign-in")

    if not db.any_users_exist():
        st.info("No admin account exists yet. Create the first HR Officer account below.")
        with st.form("first_user_form"):
            full_name = st.text_input("Full name")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account")
        if submitted:
            if not full_name or not username or not password:
                st.error("All fields are required.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                db.create_user(username, hash_password(password), full_name, role="admin")
                st.success("Account created. Please log in.")
                st.rerun()
        st.stop()

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if login(username, password):
            st.rerun()
        else:
            st.error("Invalid username or password, or account is inactive.")
    st.stop()
