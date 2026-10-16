"""
db.py — Turso (libSQL) data layer for the DBES Post-Evaluation System.

Uses the pure-Python `libsql-client` package (HTTP/WebSocket transport,
no Rust compiler needed) — same approach used for the DBES HR Forms
Dashboard on Windows.
"""

from __future__ import annotations

import os
import re
import uuid
import datetime as dt
from typing import Any, Optional

import streamlit as st
import libsql_client

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_secret(name: str) -> str:
    if name in st.secrets:
        return st.secrets[name]
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required secret/env var '{name}'. "
            "Set it in .streamlit/secrets.toml (local) or App Settings -> Secrets (Streamlit Cloud)."
        )
    return val


@st.cache_resource(show_spinner=False)
def get_client() -> "libsql_client.Client":
    url = _get_secret("TURSO_DATABASE_URL")
    token = _get_secret("TURSO_AUTH_TOKEN")
    return libsql_client.create_client_sync(url=url, auth_token=token)


def q(sql: str, params: Optional[list | dict] = None):
    """Run a query and return the ResultSet."""
    client = get_client()
    return client.execute(sql, params or [])


def qmany(statements: list[tuple[str, list]]):
    """Run several statements in a single batch (best-effort transaction)."""
    client = get_client()
    return client.batch([(sql, params) for sql, params in statements])


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin')),
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        activity_date TEXT,
        venue TEXT,
        hosting_school TEXT,
        participants TEXT,
        expected_participants INTEGER,
        status TEXT NOT NULL DEFAULT 'open',
        qr_token TEXT UNIQUE NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_questions (
        id TEXT PRIMARY KEY,
        question_text TEXT NOT NULL,
        qtype TEXT NOT NULL CHECK (qtype IN ('rating', 'multiple_choice', 'open_ended')),
        category TEXT NOT NULL,
        options TEXT,
        order_index INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_speakers (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        name TEXT NOT NULL,
        topic TEXT,
        session_number INTEGER,
        order_index INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_questions (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        question_text TEXT NOT NULL,
        qtype TEXT NOT NULL CHECK (qtype IN ('rating', 'multiple_choice', 'open_ended')),
        category TEXT NOT NULL,
        options TEXT,
        order_index INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'base',
        speaker_id TEXT REFERENCES activity_speakers(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS responses (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        participant_name TEXT,
        participant_school TEXT,
        submitted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS response_answers (
        id TEXT PRIMARY KEY,
        response_id TEXT NOT NULL REFERENCES responses(id),
        question_id TEXT NOT NULL REFERENCES activity_questions(id),
        answer_rating INTEGER,
        answer_choice TEXT,
        answer_text TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_summaries (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        category TEXT NOT NULL,
        summary_text TEXT NOT NULL,
        response_count INTEGER NOT NULL,
        generated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        username TEXT,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS email_codes (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comment_edits (
        answer_id TEXT PRIMARY KEY,
        edited_text TEXT,
        hidden INTEGER NOT NULL DEFAULT 0,
        edited_at TEXT NOT NULL
    )
    """,
]

DEFAULT_BASE_QUESTIONS = [
    # (text, qtype, category, options, order)
    ("The objectives of this activity were clearly explained.", "rating", "Content & Objectives", None, 1),
    ("The content was relevant and useful to my work.", "rating", "Content & Objectives", None, 2),
    ("The facilitator(s)/resource speaker(s) were knowledgeable.", "rating", "Facilitator", None, 3),
    ("The facilitator(s) delivered the session in an engaging way.", "rating", "Facilitator", None, 4),
    ("The venue and facilities were adequate.", "rating", "Logistics & Venue", None, 5),
    ("The schedule/time allotment was sufficient.", "rating", "Logistics & Venue", None, 6),
    ("Overall, how would you rate this activity?", "rating", "Overall", None, 7),
    ("What are your key takeaways/learning from this seminar-workshop?", "open_ended", "Strengths", None, 8),
    ("What areas need improvement?", "open_ended", "Areas to Improve", None, 9),
    ("Any other suggestions or comments?", "open_ended", "Suggestions", None, 10),
]

# Base categories that should appear BEFORE the per-speaker Session N areas
# when a new activity's question list is first built. Everything else
# (Overall, Strengths, Areas to Improve, Suggestions, and any custom base
# category added later) falls after the sessions. This gives the standard
# area order: Content & Objectives, Facilitator, Logistics & Venue,
# Session 1, Session 2, ..., Overall, Strengths, Areas to Improve, Suggestions.
PRE_SESSION_CATEGORIES = {"Content & Objectives", "Facilitator", "Logistics & Venue"}


DEFAULT_SPEAKER_QUESTIONS = [
    # (text_template, qtype, order_offset) — {speaker} is replaced with the speaker's name
    ("{speaker} was knowledgeable about the topic.", "rating", 1),
    ("{speaker} delivered the session in a clear and engaging manner.", "rating", 2),
    ("{speaker} answered questions/clarifications well.", "rating", 3),
]

# The fixed final-area order for everything that isn't a pre-session
# category or a per-speaker Session N: Overall rating first, then the
# three open-ended questions.
_END_OF_FORM_CATEGORIES = ["Overall", "Strengths", "Areas to Improve", "Suggestions"]

_SESSION_RE = re.compile(r"^Session (\d+)$")


def _display_rank(category: str, fallback_order: int = 0) -> tuple:
    """Deterministic sort key applied every time questions are read, so
    the on-screen order (evaluation form, question editor, report) is
    always: pre-session categories -> Session 1, Session 2, ... -> Overall
    -> Strengths -> Areas to Improve -> Suggestions -> anything else —
    regardless of what order_index happens to be stored in the database.
    This does not depend on any prior migration having run correctly; it
    recomputes the order at read time, so it can't drift out of sync
    again."""
    pre_order = ["Content & Objectives", "Facilitator", "Logistics & Venue"]
    if category in pre_order:
        return (0, pre_order.index(category), fallback_order)
    m = _SESSION_RE.match(category or "")
    if m:
        return (1, int(m.group(1)), fallback_order)
    if category in _END_OF_FORM_CATEGORIES:
        return (2, _END_OF_FORM_CATEGORIES.index(category), fallback_order)
    return (3, 0, fallback_order)


def _try(sql: str):
    """Run a migration statement, ignoring errors (e.g. column already renamed/exists)."""
    try:
        q(sql)
    except Exception:
        pass


def init_db():
    """Create tables if missing, migrate older column names, and seed default base questions once."""
    qmany([(s, []) for s in SCHEMA_STATEMENTS])

    # Migrate activities created before the "hosting_school"/"participants" rename
    # (previously "school"/"vicariate"). Safe to run every time — no-ops once done.
    _try("ALTER TABLE activities RENAME COLUMN school TO hosting_school")
    _try("ALTER TABLE activities RENAME COLUMN vicariate TO participants")
    _try("ALTER TABLE activities ADD COLUMN hosting_school TEXT")
    _try("ALTER TABLE activities ADD COLUMN participants TEXT")
    _try("ALTER TABLE activities ADD COLUMN expected_participants INTEGER")
    _try("ALTER TABLE activity_speakers ADD COLUMN session_number INTEGER")
    _try("ALTER TABLE activities ADD COLUMN teacher_name TEXT")
    _try("ALTER TABLE activities ADD COLUMN subject TEXT")
    _try("ALTER TABLE activities ADD COLUMN section TEXT")
    _try("ALTER TABLE activities ADD COLUMN school_year TEXT")
    _try("ALTER TABLE activities ADD COLUMN term TEXT")
    _try("ALTER TABLE responses ADD COLUMN student_email_hash TEXT")
    _try("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_eval_per_student ON responses(activity_id, student_email_hash)")

    existing = q("SELECT COUNT(*) AS c FROM base_questions")
    count = existing.rows[0][0] if existing.rows else 0
    if count == 0:
        for text, qtype, category, options, order in DEFAULT_BASE_QUESTIONS:
            q(
                "INSERT INTO base_questions (id, question_text, qtype, category, options, order_index) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [new_id(), text, qtype, category, options, order],
            )
    else:
        # The block above only ever runs once (when the table is first
        # created), so editing DEFAULT_BASE_QUESTIONS never touched a
        # database that had already been seeded — which is why the
        # open-ended questions kept showing up interleaved with the
        # ratings even after the ordering in this file was corrected.
        # This realigns the already-seeded rows every run; it's a no-op
        # once they match.
        _fix_base_question_order()
    _fix_base_question_wording()
    _seed_form6_questions()


# Question text corrections, keyed by category (there's exactly one base
# question per category here, so category is an unambiguous match key —
# unlike matching by old text, which is what silently failed before).
_WORDING_FIXES_BY_CATEGORY = {
    "Strengths": "What are your key takeaways/learning from this seminar-workshop?",
}


def _fix_base_question_wording():
    """Correct wording on base_questions rows, matched by category. Safe
    to call every run; a no-op once the wording already matches."""
    rs = q("SELECT id, category, question_text FROM base_questions")
    stmts = []
    for row_id, category, current_text in [(r[0], r[1], r[2]) for r in rs.rows]:
        target_text = _WORDING_FIXES_BY_CATEGORY.get(category)
        if target_text and current_text != target_text:
            stmts.append(("UPDATE base_questions SET question_text = ? WHERE id = ?", [target_text, row_id]))
    if stmts:
        qmany(stmts)


def fix_activity_question_wording(activity_id: str):
    """Apply the same wording corrections to an already-created activity's
    stored question copy — activity_questions snapshots its own text at
    creation time, independent of base_questions, so fixing the base
    template alone doesn't touch activities created before the fix."""
    rs = q("SELECT id, category, question_text FROM activity_questions WHERE activity_id = ?", [activity_id])
    stmts = []
    for row_id, category, current_text in [(r[0], r[1], r[2]) for r in rs.rows]:
        target_text = _WORDING_FIXES_BY_CATEGORY.get(category)
        if target_text and current_text != target_text:
            stmts.append(("UPDATE activity_questions SET question_text = ? WHERE id = ?", [target_text, row_id]))
    if stmts:
        qmany(stmts)


def _fix_base_question_order():
    """Force base_questions into the canonical CATEGORY order — Content &
    Objectives, Facilitator, Logistics & Venue, Overall, Strengths, Areas
    to Improve, Suggestions — regardless of the exact question wording.

    The previous version of this fix matched rows to DEFAULT_BASE_QUESTIONS
    by exact question_text, which silently did nothing on any database
    whose seeded wording had drifted even slightly (a trailing space, a
    reworded question, an extra/removed base question) — which is why the
    open-ended questions kept showing up sandwiched between the ratings
    even after that fix was deployed. Matching by category name instead is
    resilient to all of that: as long as a row's `category` column is one
    of the seven known category names, it gets sorted into the right
    bucket; anything in an unrecognized/custom category is pushed to the
    end, keeping its current relative order. Safe to call every run — a
    no-op once everything is already in order."""
    category_rank: dict[str, int] = {}
    for _text, _qtype, category, _options, _order in DEFAULT_BASE_QUESTIONS:
        category_rank.setdefault(category, len(category_rank))

    rs = q("SELECT id, category, order_index FROM base_questions ORDER BY order_index")
    rows = [(r[0], r[1], r[2]) for r in rs.rows]

    def _rank(row):
        _row_id, category, order_index = row
        return (category_rank.get(category, len(category_rank)), order_index)

    ordered = sorted(rows, key=_rank)
    stmts = [
        ("UPDATE base_questions SET order_index = ? WHERE id = ?", [idx + 1, row_id])
        for idx, (row_id, _category, _order_index) in enumerate(ordered)
        if idx + 1 != _order_index
    ]
    if stmts:
        qmany(stmts)


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------

def get_user_by_username(username: str) -> Optional[dict]:
    rs = q("SELECT id, username, password_hash, full_name, role, is_active FROM users WHERE username = ?", [username])
    if not rs.rows:
        return None
    r = rs.rows[0]
    return {"id": r[0], "username": r[1], "password_hash": r[2], "full_name": r[3], "role": r[4], "is_active": r[5]}


def create_user(username: str, password_hash: str, full_name: str, role: str = "admin"):
    q(
        "INSERT INTO users (id, username, password_hash, full_name, role, is_active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        [new_id(), username, password_hash, full_name, role, now()],
    )


def any_users_exist() -> bool:
    rs = q("SELECT COUNT(*) FROM users")
    return (rs.rows[0][0] if rs.rows else 0) > 0


def list_users() -> list[dict]:
    rs = q("SELECT id, username, full_name, role, is_active, created_at FROM users ORDER BY created_at")
    return [
        {"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "is_active": r[4], "created_at": r[5]}
        for r in rs.rows
    ]


def set_user_active(user_id: str, active: bool):
    q("UPDATE users SET is_active = ? WHERE id = ?", [1 if active else 0, user_id])


def update_password(user_id: str, password_hash: str):
    q("UPDATE users SET password_hash = ? WHERE id = ?", [password_hash, user_id])


# ---------------------------------------------------------------------------
# Base questions
# ---------------------------------------------------------------------------

def list_base_questions(active_only: bool = True) -> list[dict]:
    sql = "SELECT id, question_text, qtype, category, options, order_index, is_active FROM base_questions"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY order_index"
    rs = q(sql)
    rows = [
        {"id": r[0], "question_text": r[1], "qtype": r[2], "category": r[3], "options": r[4], "order_index": r[5], "is_active": r[6]}
        for r in rs.rows
    ]
    rows.sort(key=lambda r: _display_rank(r["category"], r["order_index"]))
    return rows


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

def create_activity(title, activity_type, activity_date, venue, hosting_school, participants, expected_participants, created_by) -> dict:
    activity_id = new_id()
    qr_token = uuid.uuid4().hex
    q(
        "INSERT INTO activities (id, title, activity_type, activity_date, venue, hosting_school, participants, "
        "expected_participants, status, qr_token, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        [activity_id, title, activity_type, str(activity_date), venue, hosting_school, participants,
         expected_participants, qr_token, created_by, now()],
    )
    return {"id": activity_id, "qr_token": qr_token}


def add_activity_speakers(activity_id: str, speakers: list[dict]) -> list[dict]:
    """speakers: list of dicts with name, topic, session. Returns list with generated ids, in order."""
    stmts = []
    created = []
    for idx, sp in enumerate(speakers):
        sid = new_id()
        created.append({"id": sid, "name": sp["name"], "topic": sp.get("topic"), "session": sp.get("session")})
        stmts.append((
            "INSERT INTO activity_speakers (id, activity_id, name, topic, session_number, order_index) VALUES (?, ?, ?, ?, ?, ?)",
            [sid, activity_id, sp["name"], sp.get("topic"), sp.get("session"), idx + 1],
        ))
    if stmts:
        qmany(stmts)
    return created


def get_activity_speakers(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT id, name, topic, session_number, order_index FROM activity_speakers WHERE activity_id = ? ORDER BY order_index",
        [activity_id],
    )
    return [{"id": r[0], "name": r[1], "topic": r[2], "session": r[3], "order_index": r[4]} for r in rs.rows]


def add_activity_questions(activity_id: str, questions: list[dict]):
    """questions: list of dicts with question_text, qtype, category, options, order_index, source, speaker_id (optional)"""
    stmts = []
    for qd in questions:
        stmts.append((
            "INSERT INTO activity_questions (id, activity_id, question_text, qtype, category, options, order_index, source, speaker_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [new_id(), activity_id, qd["question_text"], qd["qtype"], qd["category"], qd.get("options"),
             qd["order_index"], qd.get("source", "base"), qd.get("speaker_id")],
        ))
    if stmts:
        qmany(stmts)


def fix_activity_question_order(activity_id: str):
    """Re-sort an ALREADY-CREATED activity's stored questions into the
    canonical area order — pre-session categories, then each speaker's
    Session N (by session number), then Overall/Strengths/Areas to
    Improve/Suggestions, then any custom areas keeping their existing
    relative order — without adding, removing, or changing the wording of
    any question. Use this to repair activities created before the
    base-question ordering was corrected; new activities no longer need it."""
    questions = get_activity_questions(activity_id)
    speakers = get_activity_speakers(activity_id)
    session_rank = {f'Session {sp["session"]}': sp["order_index"] for sp in speakers if sp["session"] is not None}

    def _unique_in_order(cats):
        seen = set()
        out = []
        for c in cats:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    pre_categories = _unique_in_order(c for _, _, c, _, _ in DEFAULT_BASE_QUESTIONS if c in PRE_SESSION_CATEGORIES)
    post_categories = _unique_in_order(c for _, _, c, _, _ in DEFAULT_BASE_QUESTIONS if c not in PRE_SESSION_CATEGORIES)

    def category_rank(cat: str):
        if cat in pre_categories:
            return (0, pre_categories.index(cat))
        if cat in session_rank:
            return (1, session_rank[cat])
        if cat in post_categories:
            return (2, post_categories.index(cat))
        return (3, 0)  # unrecognized/custom area: keep relative spot, at the end

    ordered = sorted(questions, key=lambda qn: (category_rank(qn["category"]), qn["order_index"]))
    stmts = [
        ("UPDATE activity_questions SET order_index = ? WHERE id = ?", [idx + 1, qn["id"]])
        for idx, qn in enumerate(ordered)
    ]
    if stmts:
        qmany(stmts)


def list_activities(status: Optional[str] = None) -> list[dict]:
    sql = ("SELECT id, title, activity_type, activity_date, venue, hosting_school, participants, "
           "expected_participants, status, qr_token, created_at FROM activities")
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    rs = q(sql, params)
    return [
        {"id": r[0], "title": r[1], "activity_type": r[2], "activity_date": r[3], "venue": r[4],
         "hosting_school": r[5], "participants": r[6], "expected_participants": r[7], "status": r[8],
         "qr_token": r[9], "created_at": r[10]}
        for r in rs.rows
    ]


def get_activity(activity_id: str) -> Optional[dict]:
    rs = q(
        "SELECT id, title, activity_type, activity_date, venue, hosting_school, participants, expected_participants, "
        "status, qr_token, created_by, created_at FROM activities WHERE id = ?",
        [activity_id],
    )
    if not rs.rows:
        return None
    r = rs.rows[0]
    return {"id": r[0], "title": r[1], "activity_type": r[2], "activity_date": r[3], "venue": r[4],
            "hosting_school": r[5], "participants": r[6], "expected_participants": r[7], "status": r[8],
            "qr_token": r[9], "created_by": r[10], "created_at": r[11]}


def get_activity_by_token(qr_token: str) -> Optional[dict]:
    rs = q(
        "SELECT id, title, activity_type, activity_date, venue, hosting_school, participants, status, qr_token "
        "FROM activities WHERE qr_token = ?",
        [qr_token],
    )
    if not rs.rows:
        return None
    r = rs.rows[0]
    return {"id": r[0], "title": r[1], "activity_type": r[2], "activity_date": r[3], "venue": r[4],
            "hosting_school": r[5], "participants": r[6], "status": r[7], "qr_token": r[8]}


def set_activity_status(activity_id: str, status: str):
    q("UPDATE activities SET status = ? WHERE id = ?", [status, activity_id])


def update_activity(activity_id: str, title, activity_type, activity_date, venue, hosting_school,
                     participants, expected_participants):
    """Edit an already-created activity's basic details (title, type, date,
    venue, hosting school, participants description, expected participant
    count). Does not touch speakers, questions, or responses."""
    q(
        "UPDATE activities SET title = ?, activity_type = ?, activity_date = ?, venue = ?, "
        "hosting_school = ?, participants = ?, expected_participants = ? WHERE id = ?",
        [title, activity_type, str(activity_date), venue, hosting_school, participants,
         expected_participants, activity_id],
    )


def delete_activity(activity_id: str):
    """Permanently delete an activity and everything tied to it: its
    speakers, questions, all submitted responses (and their individual
    answers), and any saved qualitative summaries. Cannot be undone."""
    q(
        "DELETE FROM response_answers WHERE response_id IN "
        "(SELECT id FROM responses WHERE activity_id = ?)",
        [activity_id],
    )
    q("DELETE FROM responses WHERE activity_id = ?", [activity_id])
    q("DELETE FROM activity_questions WHERE activity_id = ?", [activity_id])
    q("DELETE FROM activity_speakers WHERE activity_id = ?", [activity_id])
    q("DELETE FROM ai_summaries WHERE activity_id = ?", [activity_id])
    q("DELETE FROM activities WHERE id = ?", [activity_id])


def get_activity_questions(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT id, question_text, qtype, category, options, order_index, speaker_id FROM activity_questions "
        "WHERE activity_id = ? ORDER BY order_index",
        [activity_id],
    )
    rows = [
        {"id": r[0], "question_text": r[1], "qtype": r[2], "category": r[3], "options": r[4], "order_index": r[5], "speaker_id": r[6]}
        for r in rs.rows
    ]
    # Always re-derive display order from category (see _display_rank) —
    # this is what fixes the evaluation form / results / report for
    # activities that were already created, without needing any one-off
    # data migration to have succeeded first.
    rows.sort(key=lambda r: _display_rank(r["category"], r["order_index"]))
    return rows


def get_speaker_rating_averages(activity_id: str) -> list[dict]:
    """One row per speaker: overall average across all of that speaker's rating questions."""
    rs = q(
        """
        SELECT sp.id, sp.name, sp.topic, sp.session_number, AVG(ra.answer_rating) AS avg_rating, COUNT(ra.answer_rating) AS n
        FROM activity_speakers sp
        LEFT JOIN activity_questions aq ON aq.speaker_id = sp.id AND aq.qtype = 'rating'
        LEFT JOIN response_answers ra ON ra.question_id = aq.id AND ra.answer_rating IS NOT NULL
        WHERE sp.activity_id = ?
        GROUP BY sp.id
        ORDER BY sp.order_index
        """,
        [activity_id],
    )
    return [{"id": r[0], "name": r[1], "topic": r[2], "session": r[3], "avg_rating": r[4], "n": r[5]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

def submit_response(activity_id: str, participant_name: str, participant_school: str, answers: list[dict]) -> str:
    """answers: list of dicts with question_id, qtype, value"""
    response_id = new_id()
    stmts = [(
        "INSERT INTO responses (id, activity_id, participant_name, participant_school, submitted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [response_id, activity_id, participant_name, participant_school, now()],
    )]
    for a in answers:
        rating = a["value"] if a["qtype"] == "rating" else None
        choice = a["value"] if a["qtype"] == "multiple_choice" else None
        text = a["value"] if a["qtype"] == "open_ended" else None
        stmts.append((
            "INSERT INTO response_answers (id, response_id, question_id, answer_rating, answer_choice, answer_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [new_id(), response_id, a["question_id"], rating, choice, text],
        ))
    qmany(stmts)
    return response_id


def count_responses(activity_id: str) -> int:
    rs = q("SELECT COUNT(*) FROM responses WHERE activity_id = ?", [activity_id])
    return rs.rows[0][0] if rs.rows else 0


def list_responses(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT id, participant_name, participant_school, submitted_at FROM responses "
        "WHERE activity_id = ? ORDER BY submitted_at DESC",
        [activity_id],
    )
    return [
        {"id": r[0], "participant_name": r[1], "participant_school": r[2], "submitted_at": r[3]}
        for r in rs.rows
    ]


def delete_response(response_id: str):
    """Delete a single response and all of its answers. Cannot be undone."""
    q("DELETE FROM response_answers WHERE response_id = ?", [response_id])
    q("DELETE FROM responses WHERE id = ?", [response_id])


def get_rating_summary(activity_id: str) -> list[dict]:
    """Average rating per rating-type question for this activity, including which speaker (if any) it's about."""
    rs = q(
        """
        SELECT aq.id, aq.question_text, aq.category, AVG(ra.answer_rating) AS avg_rating, COUNT(ra.answer_rating) AS n,
               sp.name AS speaker_name
        FROM activity_questions aq
        LEFT JOIN response_answers ra ON ra.question_id = aq.id AND ra.answer_rating IS NOT NULL
        LEFT JOIN activity_speakers sp ON sp.id = aq.speaker_id
        WHERE aq.activity_id = ? AND aq.qtype = 'rating'
        GROUP BY aq.id
        ORDER BY aq.order_index
        """,
        [activity_id],
    )
    rows = [
        {"question_id": r[0], "question_text": r[1], "category": r[2], "avg_rating": r[3], "n": r[4], "speaker_name": r[5]}
        for r in rs.rows
    ]
    rows.sort(key=lambda r: _display_rank(r["category"]))
    return rows


def get_open_ended_answers(activity_id: str, category: Optional[str] = None) -> list[dict]:
    sql = (
        "SELECT aq.category, aq.question_text, ra.answer_text FROM response_answers ra "
        "JOIN activity_questions aq ON aq.id = ra.question_id "
        "WHERE aq.activity_id = ? AND aq.qtype = 'open_ended' AND ra.answer_text IS NOT NULL AND ra.answer_text != ''"
    )
    params = [activity_id]
    if category:
        sql += " AND aq.category = ?"
        params.append(category)
    rs = q(sql, params)
    return [{"category": r[0], "question_text": r[1], "answer_text": r[2]} for r in rs.rows]


def get_school_summary(activity_id: str) -> list[dict]:
    """Number of responses per participating school for this activity, most
    represented first. Responses where the participant left school blank are
    grouped under 'Not specified' rather than dropped."""
    rs = q(
        """
        SELECT COALESCE(NULLIF(TRIM(participant_school), ''), 'Not specified') AS school, COUNT(*) AS n
        FROM responses
        WHERE activity_id = ?
        GROUP BY school
        ORDER BY n DESC, school ASC
        """,
        [activity_id],
    )
    return [{"school": r[0], "n": r[1]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Category summaries (written manually by the HR Officer, one per open-ended
# category; stored in the ai_summaries table/columns for schema continuity)
# ---------------------------------------------------------------------------

def save_ai_summary(activity_id: str, category: str, summary_text: str, response_count: int):
    q("DELETE FROM ai_summaries WHERE activity_id = ? AND category = ?", [activity_id, category])
    q(
        "INSERT INTO ai_summaries (id, activity_id, category, summary_text, response_count, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [new_id(), activity_id, category, summary_text, response_count, now()],
    )


def get_ai_summaries(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT category, summary_text, response_count, generated_at FROM ai_summaries WHERE activity_id = ? ORDER BY category",
        [activity_id],
    )
    return [{"category": r[0], "summary_text": r[1], "response_count": r[2], "generated_at": r[3]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_action(user_id: Optional[str], username: Optional[str], action: str, details: str = ""):
    q(
        "INSERT INTO audit_log (id, user_id, username, action, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [new_id(), user_id, username, action, details, now()],
    )


def list_audit_log(limit: int = 200) -> list[dict]:
    rs = q("SELECT username, action, details, created_at FROM audit_log ORDER BY created_at DESC LIMIT ?", [limit])
    return [{"username": r[0], "action": r[1], "details": r[2], "created_at": r[3]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Teacher evaluation (student-facing): teacher fields, email codes, one
# submission per student per evaluation
# ---------------------------------------------------------------------------

import hashlib
import secrets

CODE_TTL_MINUTES = 10
MAX_CODE_ATTEMPTS = 5


def create_evaluation(teacher_name, subject, section, school, school_year, term,
                      expected_students, created_by) -> dict:
    """One evaluation = one teacher + one subject + one section. Each gets
    its own qr_token, so two subjects in one section never mix."""
    title = f"{teacher_name} — {subject} ({section})"
    result = create_activity(
        title, "Teacher Evaluation", dt.date.today(), None, school, section,
        expected_students, created_by,
    )
    q(
        "UPDATE activities SET teacher_name = ?, subject = ?, section = ?, school_year = ?, term = ? WHERE id = ?",
        [teacher_name, subject, section, school_year, term, result["id"]],
    )
    return result


def get_teacher_info(activity_id: str) -> dict:
    rs = q(
        "SELECT teacher_name, subject, section, school_year, term FROM activities WHERE id = ?",
        [activity_id],
    )
    if not rs.rows:
        return {}
    r = rs.rows[0]
    return {"teacher_name": r[0], "subject": r[1], "section": r[2], "school_year": r[3], "term": r[4]}


def _email_hash(activity_id: str, email: str) -> str:
    # Hashed per evaluation: the database never stores the student's email
    # next to their answers, and the same student can't be linked across
    # different teachers' evaluations.
    return hashlib.sha256(f"{activity_id}:{email.strip().lower()}".encode("utf-8")).hexdigest()


def student_already_submitted(activity_id: str, email: str) -> bool:
    rs = q(
        "SELECT COUNT(*) FROM responses WHERE activity_id = ? AND student_email_hash = ?",
        [activity_id, _email_hash(activity_id, email)],
    )
    return (rs.rows[0][0] if rs.rows else 0) > 0


def submit_student_response(activity_id: str, email: str, answers: list[dict]) -> Optional[str]:
    """Returns the new response id, or None if this email already submitted
    for this evaluation. answers: list of dicts with question_id, qtype, value."""
    if student_already_submitted(activity_id, email):
        return None
    response_id = new_id()
    stmts = [(
        "INSERT INTO responses (id, activity_id, participant_name, participant_school, submitted_at, student_email_hash) "
        "VALUES (?, ?, NULL, NULL, ?, ?)",
        [response_id, activity_id, now(), _email_hash(activity_id, email)],
    )]
    for a in answers:
        rating = a["value"] if a["qtype"] == "rating" else None
        choice = a["value"] if a["qtype"] == "multiple_choice" else None
        text = a["value"] if a["qtype"] == "open_ended" else None
        stmts.append((
            "INSERT INTO response_answers (id, response_id, question_id, answer_rating, answer_choice, answer_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [new_id(), response_id, a["question_id"], rating, choice, text],
        ))
    try:
        qmany(stmts)
    except Exception:
        if student_already_submitted(activity_id, email):
            return None
        raise
    return response_id


def _code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email.strip().lower()}:{code}".encode("utf-8")).hexdigest()


def create_email_code(email: str) -> str:
    """Generate a 6-digit code for this email (replacing any earlier one)
    and store only its hash. The caller emails the returned code."""
    email = email.strip().lower()
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (dt.datetime.utcnow() + dt.timedelta(minutes=CODE_TTL_MINUTES)).isoformat(timespec="seconds") + "Z"
    q("DELETE FROM email_codes WHERE email = ?", [email])
    q(
        "INSERT INTO email_codes (id, email, code_hash, expires_at, attempts, created_at) VALUES (?, ?, ?, ?, 0, ?)",
        [new_id(), email, _code_hash(email, code), expires, now()],
    )
    return code


def verify_email_code(email: str, code: str) -> str:
    """Returns 'ok', 'wrong', 'expired', 'locked' (too many tries) or 'missing'."""
    email = email.strip().lower()
    rs = q("SELECT id, code_hash, expires_at, attempts FROM email_codes WHERE email = ?", [email])
    if not rs.rows:
        return "missing"
    row_id, stored_hash, expires_at, attempts = rs.rows[0]
    if attempts >= MAX_CODE_ATTEMPTS:
        return "locked"
    if now() > expires_at:
        return "expired"
    if _code_hash(email, code.strip()) != stored_hash:
        q("UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", [row_id])
        return "wrong"
    q("DELETE FROM email_codes WHERE id = ?", [row_id])
    return "ok"


# ---------------------------------------------------------------------------
# TPAS Form 6 (student evaluation of teachers) — seeded as the base questions
# ---------------------------------------------------------------------------

_CAT_A = "A. Knowledge of Subject and Teaching Style"
_CAT_B = "B. Interest and Stimulation"
_CAT_C = "C. Class Management and Organization"
_CAT_D = "D. Teacher–Student Relations"

FORM6_QUESTIONS = [
    # (text, qtype, category)
    ("A1. Has very good knowledge of the subject he or she teaches.", "rating", _CAT_A),
    ("A2. Is organized and prepared for class.", "rating", _CAT_A),
    ("A3. Uses learning materials such as presentations, pictures, charts, and illustrations to help students understand the lesson.", "rating", _CAT_A),
    ("A4. Presents the lesson in an understandable way.", "rating", _CAT_A),
    ("A5. Uses clear examples and emphasizes important points in the lesson.", "rating", _CAT_A),
    ("A6. Adjusts ways of teaching to the students’ learning abilities.", "rating", _CAT_A),
    ("B1. Shows enthusiasm about the subject.", "rating", _CAT_B),
    ("B2. Helps students to think independently.", "rating", _CAT_B),
    ("B3. Uses a variety of teaching styles and techniques.", "rating", _CAT_B),
    ("B4. Makes sure that lessons and discussions are interesting, worthwhile, and challenging.", "rating", _CAT_B),
    ("B5. Lets students share what they think or feel about the lesson.", "rating", _CAT_B),
    ("B6. Gives encouraging comments when students give correct answers or good ideas.", "rating", _CAT_B),
    ("C1. Speaks clearly.", "rating", _CAT_C),
    ("C2. Starts and ends classes on time.", "rating", _CAT_C),
    ("C3. Establishes clear guidelines for quizzes, tests, and papers.", "rating", _CAT_C),
    ("C4. Promptly informs the students of the results of tests and assignments.", "rating", _CAT_C),
    ("C5. Grades students fairly, based on how much they have actually learned or done.", "rating", _CAT_C),
    ("C6. Sees to it that all students obey school rules and regulations.", "rating", _CAT_C),
    ("C7. Maintains a reasonable level of order and discipline in class.", "rating", _CAT_C),
    ("C8. Makes sure that the classroom is clean and orderly and shows proper care for school property.", "rating", _CAT_C),
    ("D1. Makes the students feel free to ask questions.", "rating", _CAT_D),
    ("D2. Is fair in dealing with students.", "rating", _CAT_D),
    ("D3. Is available to students for guidance and assistance even outside class time.", "rating", _CAT_D),
    ("D4. Shows personal interest in students’ progress and success.", "rating", _CAT_D),
    ("D5. Reminds students about proper behavior at all times.", "rating", _CAT_D),
    ("D6. Treats students with patience and respect.", "rating", _CAT_D),
    ("D7. Reminds students to show respect and care for other people.", "rating", _CAT_D),
    ("D8. Reminds students of their responsibilities as good and worthy members of the community.", "rating", _CAT_D),
    ("Comments and suggestions for the professional development of the teacher — Teaching strategy:", "open_ended", "E. Comments: Teaching Strategy"),
    ("Comments and suggestions for the professional development of the teacher — Classroom management:", "open_ended", "E. Comments: Classroom Management"),
    ("Comments and suggestions for the professional development of the teacher — Others (please specify):", "open_ended", "E. Comments: Others"),
]


def _seed_form6_questions():
    """Replace the old seminar base questions with Form 6, once. Skips if
    Form 6 is already loaded, so it's a no-op on every later start."""
    rs = q("SELECT COUNT(*) FROM base_questions WHERE category = ?", [_CAT_A])
    if rs.rows and rs.rows[0][0] > 0:
        return
    stmts = [("DELETE FROM base_questions", [])]
    for idx, (text, qtype, category) in enumerate(FORM6_QUESTIONS, start=1):
        stmts.append((
            "INSERT INTO base_questions (id, question_text, qtype, category, options, order_index) "
            "VALUES (?, ?, ?, ?, NULL, ?)",
            [new_id(), text, qtype, category, idx],
        ))
    qmany(stmts)

# ---------------------------------------------------------------------------
# Subject-level (pooled) teacher results + comment review
# ---------------------------------------------------------------------------

def _in_clause(ids) -> str:
    return ",".join("?" for _ in ids)


def _norm(text) -> str:
    return " ".join((text or "").lower().split())


def list_teacher_subject_groups() -> list[dict]:
    """One group per teacher + subject + school year + term. All sections of
    that subject land in the same group (activity_ids)."""
    rs = q(
        "SELECT id, teacher_name, subject, school_year, term, status FROM activities "
        "WHERE activity_type = 'Teacher Evaluation' AND teacher_name IS NOT NULL "
        "ORDER BY teacher_name, subject, school_year, term"
    )
    groups: dict = {}
    for r in rs.rows:
        key = (_norm(r[1]), _norm(r[2]), _norm(r[3]), _norm(r[4]))
        g = groups.setdefault(key, {
            "teacher_name": r[1], "subject": r[2], "school_year": r[3], "term": r[4],
            "activity_ids": [], "statuses": [],
        })
        g["activity_ids"].append(r[0])
        g["statuses"].append(r[5])
    out = list(groups.values())
    for g in out:
        g["n_sections"] = len(g["activity_ids"])
        g["all_closed"] = all(s == "closed" for s in g["statuses"])
    return out


def count_responses_for(activity_ids) -> int:
    if not activity_ids:
        return 0
    rs = q(
        f"SELECT COUNT(*) FROM responses WHERE activity_id IN ({_in_clause(activity_ids)})",
        list(activity_ids),
    )
    return rs.rows[0][0] if rs.rows else 0


def get_pooled_rating_summary(activity_ids) -> list[dict]:
    """Average per question across ALL the given evaluations, pooling the
    individual student ratings (not averaging section averages). Each
    evaluation has its own copy of the questions, so they are matched by
    category + question text."""
    if not activity_ids:
        return []
    rs = q(
        f"""
        SELECT aq.category, aq.question_text, AVG(ra.answer_rating) AS avg_rating,
               COUNT(ra.answer_rating) AS n
        FROM activity_questions aq
        LEFT JOIN response_answers ra ON ra.question_id = aq.id AND ra.answer_rating IS NOT NULL
        WHERE aq.activity_id IN ({_in_clause(activity_ids)}) AND aq.qtype = 'rating'
        GROUP BY aq.category, aq.question_text
        """,
        list(activity_ids),
    )
    rows = [{"category": r[0], "question_text": r[1], "avg_rating": r[2], "n": r[3]} for r in rs.rows]
    rows.sort(key=lambda r: (r["category"], r["question_text"]))
    return rows


def get_pooled_open_ended_answers(activity_ids) -> list[dict]:
    """Comments across all given evaluations, with any HR edit applied on
    top. 'section' is for the admin review screen ONLY — never put it in a
    teacher/principal report."""
    if not activity_ids:
        return []
    rs = q(
        f"""
        SELECT ra.id, aq.category, ra.answer_text, ce.edited_text, COALESCE(ce.hidden, 0), a.section
        FROM response_answers ra
        JOIN activity_questions aq ON aq.id = ra.question_id
        JOIN activities a ON a.id = aq.activity_id
        LEFT JOIN comment_edits ce ON ce.answer_id = ra.id
        WHERE aq.activity_id IN ({_in_clause(activity_ids)}) AND aq.qtype = 'open_ended'
          AND ra.answer_text IS NOT NULL AND TRIM(ra.answer_text) != ''
        """,
        list(activity_ids),
    )
    return [
        {"id": r[0], "category": r[1], "original_text": r[2], "edited_text": r[3],
         "hidden": r[4], "section": r[5]}
        for r in rs.rows
    ]


def save_comment_edit(answer_id: str, edited_text: str, hidden: bool):
    q("DELETE FROM comment_edits WHERE answer_id = ?", [answer_id])
    q(
        "INSERT INTO comment_edits (answer_id, edited_text, hidden, edited_at) VALUES (?, ?, ?, ?)",
        [answer_id, edited_text, 1 if hidden else 0, now()],
    )


def clear_comment_edit(answer_id: str):
    q("DELETE FROM comment_edits WHERE answer_id = ?", [answer_id])
