from __future__ import annotations

import io
import os

import qrcode
import streamlit as st


ACTIVITY_TYPES = ["Program", "Activity", "Seminar", "Seminar-Workshop", "Training"]

# Hosts that only resolve on the machine running the app itself. If the
# configured base URL contains any of these, QR codes built from it will
# fail for anyone scanning from a phone off the server.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


def get_app_base_url() -> str:
    """Public base URL used to build evaluation links / QR codes, e.g.
    'https://your-app.streamlit.app'.

    Must be set via an APP_BASE_URL secret (Streamlit Cloud: app settings ->
    Secrets) or an APP_BASE_URL environment variable when self-hosting.
    Falls back to localhost for local dev only — QR codes built from that
    fallback will not work off the host machine.
    """
    try:
        if "APP_BASE_URL" in st.secrets:
            return str(st.secrets["APP_BASE_URL"]).rstrip("/")
    except Exception:
        # st.secrets raises if no secrets.toml exists at all — treat as unset.
        pass
    return os.environ.get("APP_BASE_URL", "http://localhost:8501").rstrip("/")


def base_url_is_reachable_externally() -> bool:
    """False if the configured base URL is a loopback address that only
    resolves on the machine running the app — i.e. QR codes built from it
    will show 'site can't be reached' for anyone scanning from a phone."""
    base = get_app_base_url().lower()
    return not any(host in base for host in _LOCAL_HOSTS)


def warn_if_base_url_unreachable() -> None:
    """Show a prominent, hard-to-miss warning on any page that is about to
    generate a QR code, if the configured base URL won't work for anyone
    off this machine. Call this near the top of that page."""
    if not base_url_is_reachable_externally():
        st.error(
            "⚠️ **QR codes will NOT work for attendees right now.** "
            f"Evaluation links are currently built from `{get_app_base_url()}`, "
            "which only resolves on this server — phones scanning the QR code "
            "will get \"site can't be reached.\"\n\n"
            "**Fix:** in your deployment's Secrets settings, set:\n\n"
            "```\nAPP_BASE_URL = \"https://your-app-name.streamlit.app\"\n```\n\n"
            "(use this app's real public URL), then reload this page.",
            icon="🚫",
        )


def build_evaluation_url(qr_token: str) -> str:
    base = get_app_base_url()
    return f"{base}/Evaluate?token={qr_token}"


def generate_qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


RATING_LABELS = {1: "Poor", 2: "Fair", 3: "Good", 4: "Very Good", 5: "Excellent"}


def rating_scale_help() -> str:
    return " · ".join(f"{n} = {label}" for n, label in RATING_LABELS.items())