import streamlit as st
import pandas as pd

import db
import auth
import report

auth.require_login()
user = auth.current_user()

st.title("📈 Activity Results")

activities = db.list_activities()
if not activities:
    st.info("No activities yet.")
    st.stop()

titles = {f'{a["title"]} — {a["activity_date"] or "no date"}': a for a in activities}
default_id = st.session_state.get("selected_activity_id")
default_label = next((k for k, v in titles.items() if v["id"] == default_id), list(titles.keys())[0])
choice = st.selectbox("Activity", list(titles.keys()), index=list(titles.keys()).index(default_label))
activity = titles[choice]

n_responses = db.count_responses(activity["id"])
expected = activity.get("expected_participants")

col1, col2 = st.columns(2)
with col1:
    st.metric("Total responses", n_responses)
with col2:
    if expected:
        st.metric("Response rate", f"{(n_responses / expected * 100):.0f}%",
                   help=f"{n_responses} of {expected} expected participants submitted an evaluation — "
                        "a proxy based on submissions, not a verified attendance headcount.")
    else:
        st.metric("Expected participants", "Not set")

if n_responses == 0:
    st.info("No responses yet for this activity.")
    st.stop()

st.subheader("Participating schools")
school_summary = db.get_school_summary(activity["id"])
if school_summary:
    school_df = pd.DataFrame(school_summary)
    school_df.columns = ["School", "# Responses"]
    st.dataframe(school_df, use_container_width=True, hide_index=True)
    st.caption(f"{len(school_summary)} distinct school(s) represented.")
else:
    st.caption("No responses yet.")

with st.expander("🗑️ Manage individual responses (delete a specific submission)"):
    st.caption("Use this to remove a test submission or a mistaken entry. Deleting a response cannot be undone.")
    responses = db.list_responses(activity["id"])
    pending_key = f"pending_delete_response_{activity['id']}"
    pending_id = st.session_state.get(pending_key)

    for r in responses:
        cols = st.columns([2, 2, 2, 1.3, 1.3])
        cols[0].write(r["participant_name"] or "—")
        cols[1].write(r["participant_school"] or "—")
        cols[2].write(r["submitted_at"])
        if pending_id == r["id"]:
            if cols[3].button("✅ Confirm", key=f"confirm_del_{r['id']}", type="primary"):
                db.delete_response(r["id"])
                db.log_action(
                    user["id"], user["username"], "response_deleted",
                    f'{activity["title"]} — {r["participant_name"] or "anonymous"} ({r["submitted_at"]})',
                )
                st.session_state.pop(pending_key, None)
                st.success("Response deleted.")
                st.rerun()
            if cols[4].button("✖ Cancel", key=f"cancel_del_{r['id']}"):
                st.session_state.pop(pending_key, None)
                st.rerun()
        else:
            if cols[3].button("Delete", key=f"del_{r['id']}"):
                st.session_state[pending_key] = r["id"]
                st.rerun()

st.subheader("Ratings summary")
rating_summary = db.get_rating_summary(activity["id"])
if rating_summary:
    df = pd.DataFrame(rating_summary)[["category", "question_text", "avg_rating", "n"]]
    df.columns = ["Category", "Question", "Average rating (1–5)", "# Responses"]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.caption("No rating-type questions on this activity.")

speakers = db.get_activity_speakers(activity["id"])
if speakers:
    st.subheader("Per-speaker ratings")
    speaker_avgs = db.get_speaker_rating_averages(activity["id"])
    sdf = pd.DataFrame(speaker_avgs)[["session", "name", "topic", "avg_rating", "n"]]
    sdf["session"] = sdf["session"].apply(lambda s: f"Session {s}" if s is not None else "—")
    sdf.columns = ["Session", "Speaker", "Topic", "Overall average rating (1–5)", "# Ratings"]
    st.dataframe(sdf, use_container_width=True, hide_index=True)

st.subheader("Open-ended responses")
open_answers = db.get_open_ended_answers(activity["id"])
if open_answers:
    categories = sorted(set(a["category"] for a in open_answers))
    for cat in categories:
        with st.expander(f"{cat} ({sum(1 for a in open_answers if a['category'] == cat)} responses)"):
            for a in open_answers:
                if a["category"] == cat:
                    st.write(f"- {a['answer_text']}")
else:
    st.caption("No open-ended responses yet.")

st.divider()
st.subheader("Qualitative summary")
st.caption("Write your own summary of the open-ended responses for each category below. This is what gets included in the Word report.")

existing_summaries = {s["category"]: s for s in db.get_ai_summaries(activity["id"])}

if open_answers:
    categories = sorted(set(a["category"] for a in open_answers))
    for cat in categories:
        current_text = existing_summaries.get(cat, {}).get("summary_text", "")
        with st.form(f"summary_form_{cat}"):
            st.markdown(f"**{cat}**")
            new_text = st.text_area(
                "Summary", value=current_text, key=f"summary_text_{cat}",
                label_visibility="collapsed", height=120,
                placeholder=f"Summarize the {cat.lower()} responses in your own words...",
            )
            save_clicked = st.form_submit_button("Save summary")
        if save_clicked:
            n_for_category = sum(1 for a in open_answers if a["category"] == cat)
            db.save_ai_summary(activity["id"], cat, new_text.strip(), n_for_category)
            st.success(f"Summary for '{cat}' saved.")
            st.rerun()
else:
    st.caption("No open-ended responses yet, so there's nothing to summarize.")

st.divider()
st.subheader("Report")
st.caption("Includes the quantitative summary, per-speaker breakdown, and your qualitative summary above.")
report_bytes = report.build_report(activity["id"])
st.download_button(
    "⬇️ Download Word report (.docx)",
    data=report_bytes,
    file_name=f'{activity["title"].strip().replace(" ", "_")}_Post_Evaluation_Report.docx',
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)