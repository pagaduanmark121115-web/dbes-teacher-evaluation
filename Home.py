import streamlit as st

st.set_page_config(page_title="DBES Post-Evaluation System", page_icon="📋", layout="wide")

import db
import auth

db.init_db()


def _login_gate():
    """Rendered as the default landing page when nobody is logged in and
    no evaluation token is present. Wrapping the login form as its own
    st.Page (instead of calling it inline) means it's registered in the
    same st.navigation() call as every other page, every run."""
    auth.require_login()


# Every page is declared once, up front, and registered in st.navigation()
# on EVERY run — logged in or not, token or not. Streamlit's router only
# recognizes a URL if it was part of the most recently registered page set,
# so if a page is sometimes left out (as Evaluate used to be, when nobody
# was logged in and no token was present yet), a fresh/unauthenticated
# visit straight to that URL — exactly what happens scanning a QR code —
# can briefly flash "Page not found" before the app catches up. Always
# registering the full set avoids that.
evaluate_page = st.Page("pages/evaluate.py", title="Evaluate", url_path="Evaluate", icon="📝")
gate_page = st.Page(_login_gate, title="Sign in", url_path="Home", icon="🔑", default=True)
dashboard_page = st.Page("pages/dashboard.py", title="Dashboard", url_path="Dashboard", icon="📊")
create_activity_page = st.Page("pages/create_activity.py", title="Create Activity", url_path="Create-Activity", icon="➕")
activity_results_page = st.Page("pages/activity_results.py", title="Activity Results", url_path="Activity-Results", icon="📈")
manage_users_page = st.Page("pages/manage_users.py", title="Manage Users", url_path="Manage-Users", icon="👥")
my_account_page = st.Page("pages/my_account.py", title="My Account", url_path="My-Account", icon="⚙️")
audit_log_page = st.Page("pages/audit_log.py", title="Audit Log", url_path="Audit-Log", icon="🗂️")

if auth.is_logged_in():
    pg = st.navigation(
        {
            "Evaluations": [dashboard_page, create_activity_page, activity_results_page],
            "Administration": [manage_users_page, my_account_page, audit_log_page],
            "Public form (for reference)": [evaluate_page],
        }
    )
    with st.sidebar:
        user = auth.current_user()
        st.markdown(f"**{user['full_name']}**")
        st.caption("HR Officer")
        if st.button("Log out", use_container_width=True):
            auth.logout()
            st.rerun()
else:
    # Not logged in: still register every page (Evaluate included) so the
    # router stays consistent, but keep the nav collapsed — visitors land
    # either on the evaluation form (if they came with a token) or the
    # sign-in/first-account gate.
    pg = st.navigation([gate_page, evaluate_page], position="hidden")

pg.run()