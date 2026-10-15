"""
emailer.py — sends the 6-digit verification code to a student's email
address using SMTP (e.g. a Gmail account with an App Password).

Required secrets (.streamlit/secrets.toml locally, App settings -> Secrets
on Streamlit Cloud):

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587
    SMTP_USER = "sender-address@gmail.com"
    SMTP_PASSWORD = "16-character-app-password"
    SMTP_FROM_NAME = "DBES HR"

For LOCAL TESTING ONLY you may add  DEV_SHOW_CODE = true  — the code is then
shown on screen instead of being emailed. Never leave that on when real
students use the form: anyone could skip the email check.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

import streamlit as st

CODE_MINUTES = 10


def _secret(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def is_dev_mode() -> bool:
    return str(_secret("DEV_SHOW_CODE", "")).strip().lower() in ("1", "true", "yes")


def send_code_email(to_email: str, code: str) -> tuple[bool, str]:
    """Returns (ok, error_message). error_message is safe to show to students."""
    host = _secret("SMTP_HOST")
    user = _secret("SMTP_USER")
    password = _secret("SMTP_PASSWORD")
    if not (host and user and password):
        return False, "Email sending is not set up yet. Please inform the HR office."

    try:
        port = int(_secret("SMTP_PORT", 587))
    except (TypeError, ValueError):
        port = 587
    from_name = _secret("SMTP_FROM_NAME", "DBES HR")

    msg = EmailMessage()
    msg["Subject"] = "Your DBES teacher evaluation verification code"
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_email
    msg.set_content(
        f"Your verification code is: {code}\n\n"
        f"It expires in {CODE_MINUTES} minutes. Enter it on the evaluation page to continue.\n\n"
        "If you did not request this code, you can ignore this email."
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPRecipientsRefused:
        return False, "We could not send a code to that email address. Please check it and try again."
    except smtplib.SMTPAuthenticationError:
        return False, "The system could not sign in to its email account. Please inform the HR office."
    except Exception:
        return False, "We couldn't send the code right now. Please try again in a moment."
    return True, ""
