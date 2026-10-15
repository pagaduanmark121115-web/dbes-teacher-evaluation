import datetime as dt

import streamlit as st
import pandas as pd

import db
import auth
import utils

auth.require_login()


def _parse_activity_date(date_str):
    """activities.activity_date is stored as an ISO string (from
    str(date_input_value) at creation time); st.date_input needs an
    actual date object back, so parse defensively."""
    if date_str:
        try:
            return dt.date.fromisoformat(date_str)
        except ValueError:
            pass
    return dt.date.today()

st.title("📊 Dashboard")

utils.warn_if_base_url_unreachable()

activities = db.list_activities()

if not activities:
    st.info("No activities yet. Go to **Create Activity** to set up your first evaluation.")
else:
    rows = []
    for a in activities:
        n_resp = db.count_responses(a["id"])
        expected = a.get("expected_participants")
        rows.append({
            "Title": a["title"],
            "Type": a["activity_type"],
            "Date": a["activity_date"],
            "School/Participants": a["hosting_school"] or a["participants"] or "—",
            "Status": a["status"],
            "Expected": expected or "—",
            "Responses": n_resp,
            "Response rate": f"{(n_resp / expected * 100):.0f}%" if expected else "—",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Quick access")
    titles = {f'{a["title"]} — {a["activity_date"] or "no date"}': a for a in activities}
    choice = st.selectbox("Select an activity", list(titles.keys()))
    selected = titles[choice]

    n_responses = db.count_responses(selected["id"])
    expected = selected.get("expected_participants")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Responses collected", n_responses)
    with col2:
        st.metric("Expected participants", expected if expected else "Not set")
    with col3:
        st.metric(
            "Response rate", f"{(n_responses / expected * 100):.0f}%" if expected else "—",
            help="Responses submitted ÷ expected participants — a proxy based on evaluation "
                 "submissions, not a verified attendance headcount.",
        )
    with col4:
        st.metric("Status", selected["status"])

    new_status = "closed" if selected["status"] == "open" else "open"
    if st.button(f"Mark as {new_status}"):
        db.set_activity_status(selected["id"], new_status)
        db.log_action(auth.current_user()["id"], auth.current_user()["username"], "activity_status_change",
                       f'{selected["title"]} -> {new_status}')
        st.rerun()

    speakers = db.get_activity_speakers(selected["id"])
    if speakers:
        st.caption("Speaker(s): " + " · ".join(f'Session {sp["session"]}: {sp["name"]}' for sp in speakers))

    st.image(utils.generate_qr_png_bytes(utils.build_evaluation_url(selected["qr_token"])), width=220,
              caption="Evaluation QR code")
    st.code(utils.build_evaluation_url(selected["qr_token"]), language=None)
    if st.button("Go to Activity Results →"):
        st.session_state["selected_activity_id"] = selected["id"]
        st.switch_page("pages/activity_results.py")

    with st.expander("✏️ Edit activity details"):
        st.caption(
            "Update the activity's basic details — including the expected participant count used "
            "for the response rate above. Handy for backfilling activities created before that field "
            "existed. This does not touch speakers, questions, or submitted responses."
        )
        with st.form(f"edit_activity_form_{selected['id']}"):
            edit_title = st.text_input("Title *", value=selected["title"])
            edit_type = st.selectbox(
                "Type *", utils.ACTIVITY_TYPES,
                index=utils.ACTIVITY_TYPES.index(selected["activity_type"])
                if selected["activity_type"] in utils.ACTIVITY_TYPES else 0,
            )
            edit_date = st.date_input("Date", value=_parse_activity_date(selected["activity_date"]))
            edit_venue = st.text_input("Venue", value=selected["venue"] or "")
            ecol1, ecol2 = st.columns(2)
            with ecol1:
                edit_hosting_school = st.text_input(
                    "Hosting School (leave blank if diocese-wide)", value=selected["hosting_school"] or "",
                )
            with ecol2:
                edit_participants = st.text_input(
                    "Participants of the Activity", value=selected["participants"] or "",
                )
            edit_expected = st.number_input(
                "Expected number of participants", min_value=0, step=1,
                value=selected.get("expected_participants") or 0,
                help="Leave at 0 if unknown.",
            )
            edit_submitted = st.form_submit_button("Save changes", type="primary")
        if edit_submitted:
            if not edit_title.strip():
                st.error("Title is required.")
            else:
                db.update_activity(
                    selected["id"], edit_title.strip(), edit_type, edit_date,
                    edit_venue.strip() or None, edit_hosting_school.strip() or None,
                    edit_participants.strip() or None, edit_expected or None,
                )
                db.log_action(auth.current_user()["id"], auth.current_user()["username"],
                               "activity_updated", edit_title.strip())
                st.success("Activity details updated.")
                st.rerun()

    with st.expander("🔧 Fix questions for this activity (wording / legacy order)"):
        st.caption(
            "Question order is now computed automatically every time it's displayed, so you "
            "shouldn't need this for ordering anymore. Use this button after a base question's "
            "wording is corrected (e.g. the Strengths question) to apply that same correction to "
            "this activity's own stored copy of its questions — activities snapshot their question "
            "text at creation time, so fixing the base template alone doesn't reach them."
        )
        if st.button("Apply latest question fixes to this activity", key=f"fix_order_{selected['id']}"):
            db.fix_activity_question_order(selected["id"])
            db.fix_activity_question_wording(selected["id"])
            db.log_action(auth.current_user()["id"], auth.current_user()["username"],
                           "questions_fixed", selected["title"])
            st.success("Questions corrected.")
            st.rerun()

    with st.expander("🗑️ Danger zone: delete this activity"):
        st.caption(
            "Permanently deletes this activity along with its speakers, questions, and "
            f"**all {db.count_responses(selected['id'])} submitted response(s)**. This cannot be undone."
        )
        st.caption("Copy the exact title below and paste it into the box to confirm:")
        st.code(selected["title"], language=None)
        confirm_text = st.text_input(
            "Type/paste the activity title to confirm",
            key=f"delete_confirm_{selected['id']}",
        )
        title_matches = confirm_text.strip() == selected["title"].strip()
        if st.button(
            "Delete activity permanently",
            type="primary",
            disabled=not title_matches,
            key=f"delete_btn_{selected['id']}",
        ):
            db.delete_activity(selected["id"])
            db.log_action(auth.current_user()["id"], auth.current_user()["username"],
                           "activity_deleted", selected["title"])
            st.session_state.pop("selected_activity_id", None)
            st.success(f'"{selected["title"]}" has been deleted.')
            st.rerun()