import re

import streamlit as st

import db
import utils

# ---------------------------------------------------------------------------
# Open-ended answer validation
# ---------------------------------------------------------------------------
MIN_WORDS = 3
MIN_CHARS = 10


def _is_low_effort_answer(text: str) -> bool:
    """True if the answer doesn't look like a real, complete response:
    blank/whitespace-only, too short, fewer than a few words, no letters
    at all, or mostly one repeated character (e.g. 'aaaaaaaa', '.......',
    a string of spaces)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if len(cleaned) < MIN_CHARS:
        return True
    words = [w for w in re.split(r"\s+", cleaned) if w]
    if len(words) < MIN_WORDS:
        return True
    if not re.search(r"[A-Za-z]", cleaned):
        return True
    letters_only = re.sub(r"[^A-Za-z]", "", cleaned).lower()
    if letters_only:
        most_common_count = max(letters_only.count(c) for c in set(letters_only))
        if most_common_count / len(letters_only) > 0.6:
            return True
    return False


db.init_db()

token = st.query_params.get("token")

if not token:
    st.error("No activity specified. Please scan the QR code provided at the venue.")
    st.stop()

activity = db.get_activity_by_token(token)

if not activity:
    st.error("This evaluation link is invalid.")
    st.stop()

if activity["status"] != "open":
    st.warning("This evaluation is no longer accepting responses. Thank you for your interest.")
    st.stop()

st.title(activity["title"])
meta_bits = [b for b in [activity["activity_type"], activity["activity_date"], activity["venue"]] if b]
st.caption(" · ".join(meta_bits))

speakers = db.get_activity_speakers(activity["id"])
if speakers:
    speaker_bits = [f'Session {sp["session"]}: {sp["name"]}' + (f' ({sp["topic"]})' if sp["topic"] else "") for sp in speakers]
    st.caption("Speaker(s): " + " · ".join(speaker_bits))

st.write("Thank you for attending. Please take a moment to complete this post-evaluation.")

st.caption(
    "🔒 **Data Privacy Notice.** In compliance with the Data Privacy Act of 2012 (Republic Act No. 10173), "
    "the information you provide in this evaluation form will be collected and processed solely for the "
    "purpose of assessing and improving DBES programs, activities, seminars, and trainings. Your responses "
    "will be kept confidential and will not be shared with third parties, except as required by law or with "
    "your consent."
)

if st.session_state.get(f"submitted_{activity['id']}"):
    st.success("Your response has been recorded. Thank you!")
    st.stop()

questions = db.get_activity_questions(activity["id"])

with st.form("eval_form"):
    st.subheader("Your information")
    name = st.text_input("Name")
    school = st.text_input("School")

    st.divider()
    st.subheader("Evaluation")
    st.caption("Fields marked * are required. Please select a rating for each rating question, and answer open-ended questions in a complete sentence — a single word, symbols, or blank spaces will not be accepted.")
    st.info(f"**Rating scale:** {utils.rating_scale_help()}", icon="⭐")

    answers = {}
    current_category = None
    for qn in questions:
        if qn["category"] != current_category:
            st.markdown(f"**{qn['category']}**")
            current_category = qn["category"]

        if qn["qtype"] == "rating":
            st.markdown(f'{qn["question_text"]} *')
            answers[qn["id"]] = st.segmented_control(
                qn["question_text"], options=[1, 2, 3, 4, 5],
                key=f"q_{qn['id']}", label_visibility="collapsed",
            )
        elif qn["qtype"] == "multiple_choice":
            options = (qn["options"] or "").split("|") if qn["options"] else ["Yes", "No"]
            answers[qn["id"]] = st.radio(qn["question_text"], options, key=f"q_{qn['id']}")
        else:
            answers[qn["id"]] = st.text_area(
                f'{qn["question_text"]} *', key=f"q_{qn['id']}",
                help="Please write a complete sentence (at least a few words).",
            )

    submitted = st.form_submit_button("Submit evaluation", type="primary")

if submitted:
    missing_ratings = [
        qn["question_text"] for qn in questions
        if qn["qtype"] == "rating" and answers.get(qn["id"]) is None
    ]
    missing_open = [
        qn["question_text"] for qn in questions
        if qn["qtype"] == "open_ended" and _is_low_effort_answer(answers.get(qn["id"]))
    ]
    if missing_ratings or missing_open:
        error_parts = []
        if missing_ratings:
            error_parts.append(
                "Please select a rating for the following question(s):\n\n"
                + "\n".join(f"- {m}" for m in missing_ratings)
            )
        if missing_open:
            error_parts.append(
                "Please provide a complete, meaningful answer (not just a word, symbols, or spaces) "
                "for the following required question(s):\n\n"
                + "\n".join(f"- {m}" for m in missing_open)
            )
        st.error("\n\n".join(error_parts))
    else:
        formatted = [{"question_id": qid, "qtype": next(q["qtype"] for q in questions if q["id"] == qid), "value": val}
                     for qid, val in answers.items()]
        db.submit_response(activity["id"], name.strip() or None, school.strip() or None, formatted)
        st.session_state[f"submitted_{activity['id']}"] = True
        st.rerun()