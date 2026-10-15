import streamlit as st

import db
import auth
import utils

auth.require_login()
user = auth.current_user()

st.title("➕ Create Evaluation")
st.caption(
    "Set up one evaluation for one teacher, one subject and one section. Each evaluation gets its "
    "own QR code and link, so two subjects taught by the same teacher to the same section never mix."
)

utils.warn_if_base_url_unreachable()

with st.form("create_evaluation_form"):
    teacher_name = st.text_input("Teacher's name *")
    subject = st.text_input("Subject taught *")
    section = st.text_input("Section handled *")
    school = st.text_input("School *")
    col1, col2 = st.columns(2)
    school_year = col1.text_input("School year *", value=utils.default_school_year())
    term = col2.selectbox("Term *", utils.TERMS)
    expected_students = st.number_input(
        "Number of students in this section", min_value=0, step=1, value=0,
        help="Used to compute the response rate. Leave at 0 if unknown.",
    )
    submitted = st.form_submit_button("Generate evaluation & QR code", type="primary")

if submitted:
    teacher_name = teacher_name.strip()
    subject = subject.strip()
    section = section.strip()
    school = school.strip()
    school_year = school_year.strip()

    if not (teacher_name and subject and section and school and school_year):
        st.error("Teacher's name, subject, section, school and school year are all required.")
    else:
        base_questions = db.list_base_questions()
        if not base_questions:
            st.error("The Form 6 questions have not been loaded. Restart the app and try again.")
        else:
            result = db.create_evaluation(
                teacher_name, subject, section, school, school_year, term,
                expected_students or None, created_by=user["id"],
            )
            db.add_activity_questions(result["id"], [
                {
                    "question_text": bq["question_text"],
                    "qtype": bq["qtype"],
                    "category": bq["category"],
                    "options": bq.get("options"),
                    "order_index": idx + 1,
                    "source": "base",
                }
                for idx, bq in enumerate(base_questions)
            ])
            db.log_action(
                user["id"], user["username"], "evaluation_created",
                f"{teacher_name} — {subject} ({section}), {school_year} {term}",
            )

            st.success(
                f"Evaluation created for {teacher_name} — {subject} ({section}) "
                f"with {len(base_questions)} Form 6 items."
            )
            eval_url = utils.build_evaluation_url(result["qr_token"])
            st.image(utils.generate_qr_png_bytes(eval_url), width=260, caption="Scan to evaluate")
            st.code(eval_url, language=None)
            st.caption("You can show this QR code and link again anytime from the Dashboard.")
