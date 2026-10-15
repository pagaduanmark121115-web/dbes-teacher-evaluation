import datetime as dt

import streamlit as st

import db
import auth
import utils

auth.require_login()
user = auth.current_user()

st.title("➕ Create Activity")
st.caption("Set up a program, activity, seminar, or training and generate its evaluation QR code.")

utils.warn_if_base_url_unreachable()

# ---------------------------------------------------------------------------
# Step 1 — Activity details
# ---------------------------------------------------------------------------

with st.form("activity_details"):
    st.subheader("1. Activity details")
    title = st.text_input("Title *")
    activity_type = st.selectbox("Type *", utils.ACTIVITY_TYPES)
    activity_date = st.date_input("Date", value=dt.date.today())
    venue = st.text_input("Venue")
    col1, col2 = st.columns(2)
    with col1:
        hosting_school = st.text_input("Hosting School (leave blank if diocese-wide)")
    with col2:
        participants = st.text_input("Participants of the Activity", placeholder="e.g. School Principals, Grade 7-10 Teachers")
    expected_participants = st.number_input(
        "Expected number of participants", min_value=0, step=1, value=0,
        help="Used to compute the attendance rate on the Dashboard once responses come in. Leave at 0 if unknown.",
    )
    details_submitted = st.form_submit_button("Save details & continue to speakers")

if details_submitted:
    title = title.strip()
    if not title:
        st.error("Title is required.")
    else:
        st.session_state["pending_activity"] = {
            "title": title,
            "activity_type": activity_type,
            "activity_date": activity_date,
            "venue": venue,
            "hosting_school": hosting_school.strip() or None,
            "participants": participants.strip() or None,
            "expected_participants": expected_participants or None,
        }
        st.session_state.pop("questions_ready", None)
        st.success("Details saved. Add the speaker(s) below.")

# ---------------------------------------------------------------------------
# Step 2 — Speakers (one or more), each assigned to a session
# ---------------------------------------------------------------------------

MAX_SESSIONS = 10

if "pending_activity" in st.session_state and not st.session_state.get("questions_ready"):
    st.divider()
    st.subheader("2. Speaker(s)")
    st.caption(
        "Add every speaker/facilitator/resource person for this activity and assign each one a session. "
        "Each speaker's questions will appear under their session heading, answered individually by participants."
    )

    if "draft_speakers" not in st.session_state:
        st.session_state["draft_speakers"] = []

    used_sessions = {sp["session"] for sp in st.session_state["draft_speakers"]}
    next_session = next((n for n in range(1, MAX_SESSIONS + 1) if n not in used_sessions), 1)

    for i, sp in enumerate(st.session_state["draft_speakers"]):
        cols = st.columns([1.4, 2.6, 2.6, 1])
        cols[0].text_input("Session", value=f'Session {sp["session"]}', key=f"sp_session_{i}", disabled=True)
        cols[1].text_input("Speaker name", value=sp["name"], key=f"sp_name_{i}", disabled=True)
        cols[2].text_input("Topic (optional)", value=sp.get("topic") or "", key=f"sp_topic_{i}", disabled=True)
        if cols[3].button("Remove", key=f"sp_remove_{i}"):
            st.session_state["draft_speakers"].pop(i)
            st.rerun()

    with st.form("add_speaker_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1.4, 2.6, 2.6, 1])
        session_choice = c1.selectbox(
            "Session", [f"Session {n}" for n in range(1, MAX_SESSIONS + 1)],
            index=next_session - 1,
        )
        new_name = c2.text_input("Speaker name")
        new_topic = c3.text_input("Topic (optional)")
        add_speaker_clicked = c4.form_submit_button("Add speaker")
    if add_speaker_clicked and new_name.strip():
        session_num = int(session_choice.split(" ")[1])
        st.session_state["draft_speakers"].append({
            "name": new_name.strip(), "topic": new_topic.strip() or None, "session": session_num,
        })
        st.session_state["draft_speakers"].sort(key=lambda s: s["session"])
        st.rerun()

    st.caption(f"{len(st.session_state['draft_speakers'])} speaker(s) added.")

    if st.button("Continue to evaluation questions →", type="primary",
                 disabled=len(st.session_state["draft_speakers"]) == 0):
        base_questions = db.list_base_questions()
        pre_session = [bq for bq in base_questions if bq["category"] in db.PRE_SESSION_CATEGORIES]
        post_session = [bq for bq in base_questions if bq["category"] not in db.PRE_SESSION_CATEGORIES]

        draft = [{**bq, "source": "base", "include": True, "speaker_index": None, "uid": db.new_id()} for bq in pre_session]

        order = len(draft) + 1
        for s_idx, sp in enumerate(st.session_state["draft_speakers"]):
            for text_template, qtype, _offset in db.DEFAULT_SPEAKER_QUESTIONS:
                draft.append({
                    "id": None,
                    "question_text": text_template.format(speaker=sp["name"]),
                    "qtype": qtype,
                    "category": f'Session {sp["session"]}',
                    "options": None,
                    "order_index": order,
                    "source": "speaker",
                    "include": True,
                    "speaker_index": s_idx,
                    "uid": db.new_id(),
                })
                order += 1

        draft += [{**bq, "source": "base", "include": True, "speaker_index": None, "uid": db.new_id()} for bq in post_session]

        st.session_state["draft_questions"] = draft
        st.session_state["questions_ready"] = True
        st.rerun()

    if not st.session_state["draft_speakers"]:
        st.info("Add at least one speaker to continue. Most trainings will have 2 or more — pick a session for each.")

# ---------------------------------------------------------------------------
# Step 3 — Evaluation questions (filled in / edited manually, no auto-reorder tool)
# ---------------------------------------------------------------------------

if st.session_state.get("questions_ready"):
    st.divider()
    st.subheader("3. Evaluation questions")
    st.caption(
        "Areas appear in this order: Content & Objectives, Facilitator, Logistics & Venue, each speaker's "
        "Session, then Overall, Strengths, Areas to Improve, and Suggestions. "
        "Uncheck to exclude a question, edit its text/category/type inline, and use the **+ Add** box under "
        "each area to insert a new question directly there. Need an area that isn't listed? Use "
        "'Add a question under a brand-new area' at the bottom."
    )

    if st.button("← Back to speakers"):
        st.session_state.pop("questions_ready", None)
        st.session_state.pop("draft_questions", None)
        st.rerun()

    def _insert_into_category(question, category):
        """Insert a new question right after the last existing question of
        the same category, so storage order matches the on-screen grouping."""
        dq_list = st.session_state["draft_questions"]
        last_idx = None
        for i, dq in enumerate(dq_list):
            if dq["category"] == category:
                last_idx = i
        if last_idx is None:
            dq_list.append(question)
        else:
            dq_list.insert(last_idx + 1, question)

    # Areas in the order they first appear
    categories_order = []
    for dq in st.session_state["draft_questions"]:
        if dq["category"] not in categories_order:
            categories_order.append(dq["category"])

    updated_by_uid = {}
    for cat in categories_order:
        st.markdown(f"**{cat}**")
        cat_questions = [dq for dq in st.session_state["draft_questions"] if dq["category"] == cat]
        for dq in cat_questions:
            cols = st.columns([0.5, 3, 1.3, 1.3])
            include = cols[0].checkbox("Use", value=dq["include"], key=f"inc_{dq['uid']}")
            text = cols[1].text_input("Question", value=dq["question_text"], key=f"txt_{dq['uid']}", label_visibility="collapsed")
            category = cols[2].text_input("Category", value=dq["category"], key=f"cat_{dq['uid']}", label_visibility="collapsed")
            qtype = cols[3].selectbox("Type", ["rating", "multiple_choice", "open_ended"],
                                       index=["rating", "multiple_choice", "open_ended"].index(dq["qtype"]),
                                       key=f"typ_{dq['uid']}", label_visibility="collapsed")
            updated_by_uid[dq["uid"]] = {**dq, "include": include, "question_text": text, "category": category, "qtype": qtype}

        with st.form(f"add_q_form_{cat}", clear_on_submit=True):
            ac1, ac2, ac3 = st.columns([4, 1.5, 1])
            new_text = ac1.text_input(
                "Question text", key=f"new_text_{cat}", label_visibility="collapsed",
                placeholder=f"+ Add a question under '{cat}'...",
            )
            new_type = ac2.selectbox(
                "Type", ["rating", "multiple_choice", "open_ended"],
                key=f"new_type_{cat}", label_visibility="collapsed",
            )
            add_clicked = ac3.form_submit_button("Add here")
        if add_clicked and new_text.strip():
            _insert_into_category({
                "id": None, "question_text": new_text.strip(), "qtype": new_type,
                "category": cat, "options": None, "order_index": 0,
                "source": "custom", "include": True, "speaker_index": None, "uid": db.new_id(),
            }, cat)
            st.rerun()

        st.write("")

    # Persist any inline edits made above, preserving stored order
    st.session_state["draft_questions"] = [
        updated_by_uid.get(dq["uid"], dq) for dq in st.session_state["draft_questions"]
    ]

    st.divider()
    st.markdown("**Add a question under a brand-new area**")
    st.caption("Only needed if the question doesn't belong to any of the areas above — this creates a new area.")
    with st.form("add_question_new_category_form", clear_on_submit=True):
        nc1, nc2, nc3 = st.columns([3, 1.5, 1.5])
        nc_text = nc1.text_input("Question text")
        nc_category = nc2.text_input("New area name")
        nc_type = nc3.selectbox("Type", ["rating", "multiple_choice", "open_ended"])
        nc_add_clicked = st.form_submit_button("Add new area")
    if nc_add_clicked:
        if not nc_text.strip() or not nc_category.strip():
            st.error("Both question text and a new area name are required.")
        else:
            st.session_state["draft_questions"].append({
                "id": None, "question_text": nc_text.strip(), "qtype": nc_type,
                "category": nc_category.strip(), "options": None,
                "order_index": len(st.session_state["draft_questions"]) + 1,
                "source": "custom", "include": True, "speaker_index": None, "uid": db.new_id(),
            })
            st.rerun()

    st.divider()
    if st.button("✅ Generate activity & QR code", type="primary"):
        pa = st.session_state["pending_activity"]
        result = db.create_activity(
            pa["title"], pa["activity_type"], pa["activity_date"], pa["venue"], pa["hosting_school"], pa["participants"],
            pa["expected_participants"], created_by=user["id"],
        )

        created_speakers = db.add_activity_speakers(result["id"], st.session_state["draft_speakers"])

        final_questions = []
        for idx, dq in enumerate(q for q in st.session_state["draft_questions"] if q["include"]):
            speaker_id = None
            if dq.get("speaker_index") is not None:
                speaker_id = created_speakers[dq["speaker_index"]]["id"]
            final_questions.append({
                "question_text": dq["question_text"],
                "qtype": dq["qtype"],
                "category": dq["category"],
                "options": dq.get("options"),
                "order_index": idx + 1,
                "source": dq["source"],
                "speaker_id": speaker_id,
            })
        db.add_activity_questions(result["id"], final_questions)
        db.log_action(user["id"], user["username"], "activity_created",
                       f'{pa["title"]} ({len(created_speakers)} speaker(s))')

        st.success(f"Activity '{pa['title']}' created with {len(created_speakers)} speaker(s) and {len(final_questions)} question(s).")
        eval_url = utils.build_evaluation_url(result["qr_token"])
        st.image(utils.generate_qr_png_bytes(eval_url), width=260, caption="Scan to evaluate")
        st.code(eval_url, language=None)

        for key in ("pending_activity", "draft_speakers", "draft_questions", "questions_ready"):
            st.session_state.pop(key, None)