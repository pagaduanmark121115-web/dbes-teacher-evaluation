import re
import time

import streamlit as st

import db
import utils
import emailer

RESEND_SECONDS = 60
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

db.init_db()

token = st.query_params.get("token")

if not token:
    st.error("No evaluation specified. Please scan the QR code or use the link given by your teacher/school.")
    st.stop()

activity = db.get_activity_by_token(token)

if not activity:
    st.error("This evaluation link is invalid.")
    st.stop()

if activity["status"] != "open":
    st.warning("This evaluation is no longer accepting responses. Thank you.")
    st.stop()

aid = activity["id"]
info = db.get_teacher_info(aid)

# --- Header ---------------------------------------------------------------
st.title("Student Evaluation of Teacher")
st.subheader(info.get("teacher_name") or activity["title"])
header_bits = [
    info.get("subject"), info.get("section"), activity.get("hosting_school"),
    " ".join(b for b in [info.get("school_year"), info.get("term")] if b),
]
st.caption(" · ".join(b for b in header_bits if b))

st.caption(
    "🔒 **Data Privacy Notice.** In compliance with the Data Privacy Act of 2012 (Republic Act No. 10173), "
    "your responses are collected solely to assess and help improve teaching. Your email address is used only "
    "to confirm that you are a real respondent and to allow one evaluation per teacher and subject. It is not "
    "saved together with your answers, and your teacher will not see who submitted which response."
)

if st.session_state.get(f"submitted_{aid}"):
    st.success("Thank you! Your evaluation has been recorded.")
    st.stop()

# --- Step 1: verify email ---------------------------------------------------
verified_key = f"verified_email_{aid}"
pending_key = f"pending_email_{aid}"
sent_key = f"last_sent_{aid}"
dev_code_key = f"dev_code_{aid}"

verified_email = st.session_state.get(verified_key)

if not verified_email:
    st.subheader("Step 1: Verify your email")
    st.caption("Enter your email address. We will send a 6-digit code to confirm it.")

    email_input = st.text_input("Your email address", key=f"email_{aid}", placeholder="name@gmail.com")
    pending = st.session_state.get(pending_key)
    wait = int(RESEND_SECONDS - (time.time() - st.session_state.get(sent_key, 0.0)))

    if st.button("Resend code" if pending else "Send verification code"):
        email = email_input.strip().lower()
        if not EMAIL_RE.match(email):
            st.error("Please enter a valid email address.")
        elif pending and email == pending and wait > 0:
            st.warning(f"Please wait {wait} more second(s) before requesting a new code.")
        elif db.student_already_submitted(aid, email):
            st.error("This email address has already submitted an evaluation for this teacher and subject.")
        else:
            code = db.create_email_code(email)
            if emailer.is_dev_mode():
                st.session_state[dev_code_key] = code
                ok, err = True, ""
            else:
                ok, err = emailer.send_code_email(email, code)
            if ok:
                st.session_state[pending_key] = email
                st.session_state[sent_key] = time.time()
                pending = email
            else:
                st.error(err)

    if pending:
        st.info(
            f"A 6-digit code was sent to **{pending}**. It expires in {db.CODE_TTL_MINUTES} minutes. "
            "Check your inbox and spam folder."
        )
        if st.session_state.get(dev_code_key):
            st.warning(f"DEVELOPMENT MODE — your code is {st.session_state[dev_code_key]}. Turn off DEV_SHOW_CODE before real use.")

        code_input = st.text_input("Enter the 6-digit code", key=f"code_{aid}", max_chars=6)
        if st.button("Verify code", type="primary"):
            result = db.verify_email_code(pending, code_input)
            if result == "ok":
                st.session_state[verified_key] = pending
                st.rerun()
            elif result == "wrong":
                st.error("That code is not correct. Please try again.")
            elif result == "expired":
                st.error("That code has expired. Please request a new one.")
            elif result == "locked":
                st.error("Too many incorrect attempts. Please request a new code.")
            else:
                st.error("No code found for this email. Please request a new one.")
    st.stop()

# --- Step 2: the evaluation form ---------------------------------------------
st.success(f"Email verified: {verified_email}")
st.subheader("Step 2: Evaluation")
st.caption(
    "Rate how often your teacher shows each behavior. Every rating is required. "
    "The comment boxes at the end are optional. Your name, email and section are never shown with your "
    "answers, but your comments will be shared word for word with your teacher and the principal, "
    "so please do not write names or details that could identify you."
)
st.info(f"**Rating scale:** {utils.rating_scale_help()}", icon="⭐")

questions = db.get_activity_questions(aid)
qtype_by_id = {qn["id"]: qn["qtype"] for qn in questions}

with st.form("eval_form"):
    answers = {}
    current_category = None
    for qn in questions:
        if qn["category"] != current_category:
            st.markdown(f"**{qn['category']}**")
            if qn["qtype"] == "rating":
                st.caption("The teacher…")
            current_category = qn["category"]

        if qn["qtype"] == "rating":
            st.markdown(qn["question_text"])
            answers[qn["id"]] = st.segmented_control(
                qn["question_text"], options=[1, 2, 3, 4, 5],
                key=f"q_{qn['id']}", label_visibility="collapsed",
            )
        elif qn["qtype"] == "multiple_choice":
            options = (qn["options"] or "").split("|") if qn["options"] else ["Yes", "No"]
            answers[qn["id"]] = st.radio(qn["question_text"], options, key=f"q_{qn['id']}")
        else:
            answers[qn["id"]] = st.text_area(qn["question_text"], key=f"q_{qn['id']}")

    submitted = st.form_submit_button("Submit evaluation", type="primary")

if submitted:
    missing = [
        qn["question_text"] for qn in questions
        if qn["qtype"] == "rating" and answers.get(qn["id"]) is None
    ]
    if missing:
        st.error(
            "Please select a rating for the following item(s):\n\n"
            + "\n".join(f"- {m}" for m in missing)
        )
    else:
        formatted = []
        for qid, val in answers.items():
            if qtype_by_id[qid] == "open_ended":
                val = (val or "").strip() or None
            formatted.append({"question_id": qid, "qtype": qtype_by_id[qid], "value": val})

        response_id = db.submit_student_response(aid, verified_email, formatted)
        if response_id is None:
            st.error("This email address has already submitted an evaluation for this teacher and subject.")
        else:
            st.session_state[f"submitted_{aid}"] = True
            st.session_state.pop(verified_key, None)
            st.rerun()
