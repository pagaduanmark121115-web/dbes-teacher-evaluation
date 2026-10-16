import streamlit as st
import pandas as pd

import db
import auth
import subject_report

auth.require_login()
user = auth.current_user()

st.title("🧑‍🏫 Teacher Reports")
st.caption(
    "One result per teacher per subject. All sections of the same subject are pooled, and the "
    "section is never shown in the report. Sections are visible on this page only for you."
)

groups = db.list_teacher_subject_groups()
if not groups:
    st.info("No teacher evaluations yet.")
    st.stop()

labels = {
    f'{g["teacher_name"]} — {g["subject"]} ({g["school_year"] or ""} {g["term"] or ""})'.replace("  ", " "): g
    for g in groups
}
group = labels[st.selectbox("Teacher and subject", list(labels.keys()))]
ids = group["activity_ids"]
n = db.count_responses_for(ids)

c1, c2, c3 = st.columns(3)
c1.metric("Respondents (all sections)", n)
c2.metric("Sections", group["n_sections"])
c3.metric("Status", "All closed" if group["all_closed"] else "Still open")

with st.expander("🔒 Admin only: responses per section"):
    for aid in ids:
        info = db.get_teacher_info(aid)
        st.write(f'{info.get("section")}: {db.count_responses(aid)} response(s)')

st.subheader("Pooled ratings for this subject")
rating_rows = db.get_pooled_rating_summary(ids)
if rating_rows and n:
    overall = subject_report.weighted_average(rating_rows)
    if overall is not None:
        st.metric("Overall average", f"{overall:.2f}")
    df = pd.DataFrame(rating_rows)[["category", "question_text", "avg_rating", "n"]]
    df.columns = ["Category", "Question", "Average rating (1–5)", "# Ratings"]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.caption("No responses yet.")

st.divider()
st.subheader("Review comments before release")
st.caption(
    "Edit a comment to replace any detail that could identify a student with [removed], or hide it. "
    "This changes only the report copy; the original is kept. Sections are shown here for you only."
)
answers = db.get_pooled_open_ended_answers(ids)
if not answers:
    st.caption("No comments yet.")
for cat in sorted({a["category"] for a in answers}):
    items = [a for a in answers if a["category"] == cat]
    with st.expander(f"{cat} ({len(items)})"):
        for a in items:
            current = a["edited_text"] if a["edited_text"] is not None else a["original_text"]
            with st.form(f"comment_form_{a['id']}"):
                flags = []
                if a["edited_text"] is not None:
                    flags.append("✏️ edited")
                if a["hidden"]:
                    flags.append("🙈 hidden")
                st.caption(f"Section: {a['section']} (admin only)" + (" · " + " · ".join(flags) if flags else ""))
                new_text = st.text_area("Comment as it will appear in the report", value=current,
                                        key=f"ct_{a['id']}", height=80)
                hide = st.checkbox("Hide this comment from the report", value=bool(a["hidden"]),
                                   key=f"ch_{a['id']}")
                b1, b2 = st.columns(2)
                save = b1.form_submit_button("Save")
                restore = b2.form_submit_button("Restore original")
            if a["edited_text"] is not None:
                st.caption(f"Original: {a['original_text']}")
            if save:
                if new_text.strip() == a["original_text"].strip() and not hide:
                    db.clear_comment_edit(a["id"])
                else:
                    db.save_comment_edit(a["id"], new_text.strip(), hide)
                db.log_action(user["id"], user["username"], "comment_edited",
                              f'{group["teacher_name"]} — {group["subject"]}')
                st.rerun()
            if restore:
                db.clear_comment_edit(a["id"])
                st.rerun()

st.divider()
st.subheader("Report for the teacher and principal")
if not group["all_closed"]:
    st.warning("Some sections are still open. Close each one from the Dashboard (Mark as closed) first.")
elif n < subject_report.MIN_RESPONDENTS:
    st.warning(f"Only {n} respondent(s). The report is released at {subject_report.MIN_RESPONDENTS} or more.")
else:
    st.download_button(
        "⬇️ Download report (.docx)",
        data=subject_report.build_subject_report(group),
        file_name=f'{group["teacher_name"].strip().replace(" ", "_")}_{group["subject"].strip().replace(" ", "_")}_Evaluation_Report.docx',
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
