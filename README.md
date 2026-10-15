# DBES Post-Evaluation System

Automatic post-evaluation for programs, activities, seminars, and trainings
conducted by the Diocese of Bayombong Education System (DBES). The HR
Officer creates an activity, the app generates a QR code, participants scan
it and fill out a short evaluation (no login needed), and responses are
collated automatically.

**Stack:** Streamlit, Turso (libSQL), Python, deployed via GitHub + Streamlit
Community Cloud.

## Status: Step 1 (this build)

- ✅ Project scaffold, Turso schema, seeded default evaluation questions
- ✅ HR Officer / Admin authentication (first-run account creation, login,
  Manage Users, My Account, Audit Log)
- ✅ **Create Activity**: enter activity details, add **2 or more speakers**
  (each auto-gets their own rating questions), review/edit/exclude the
  base evaluation questions, add custom questions for that activity, and
  generate its unique QR code
- ✅ **Evaluate**: the public, no-login page participants land on after
  scanning the QR code — speakers are listed, and each speaker's questions
  are answered individually
- ✅ **Dashboard**: list of activities, response counts, speaker names, QR
  code re-display
- ✅ **Activity Results**: response count, average ratings per question,
  a dedicated per-speaker ratings breakdown, and open-ended answers grouped
  by category
- ✅ **Qualitative summary**: the HR Officer writes their own short summary
  per open-ended category directly on the Activity Results page (not
  AI-generated — by design, so the HR Officer controls the wording)
- ✅ **Word report export**: one click downloads a formatted .docx report
  combining activity details, quantitative summary, per-speaker ratings,
  and the qualitative summary

## Step 3: Deployment

See the **Deploying to Streamlit Community Cloud** section below.

## Local setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Create a Turso database (https://turso.tech) and grab its URL + auth
   token.
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and
   fill in:
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
   - `APP_BASE_URL` (use `http://localhost:8501` for local dev)
4. Run the app:
   ```
   streamlit run Home.py
   ```
5. On first run, you'll be prompted to create the first HR Officer account.

## Deploying to Streamlit Community Cloud

1. Push this project to a GitHub repo.
2. Create a new app on Streamlit Community Cloud pointing at `Home.py`.
3. In **App settings → Secrets**, paste the same keys as in
   `secrets.toml.example`, but set `APP_BASE_URL` to your deployed app's
   URL (e.g. `https://dbes-post-eval.streamlit.app`) — this is what gets
   encoded into every QR code, so it must be correct before generating
   activities for real use.
4. Deploy. The **Evaluate** page is reachable by anyone with the link/QR
   code; every other page requires HR Officer login.

## Project structure

```
Home.py                  Entry point, navigation, login gate
db.py                     Turso/libSQL data layer + schema
auth.py                   Login, password hashing, session handling
utils.py                  QR code generation, constants
pages/
  dashboard.py            Activity list, QR re-display, response counts
  create_activity.py      Activity details + question builder + QR generation
  evaluate.py              Public evaluation form (no login)
  activity_results.py     Quant summary + open-ended answers
  manage_users.py         HR Officer account management
  my_account.py            Change password
  audit_log.py             Action history
```

## Notes

- Only one role exists in this app: HR Officer/Admin. School Principals do
  not get accounts here — they can view results only through reports the
  HR Officer shares with them (matches the "Only HR Officer/Admin manage
  activities" decision).
- The evaluation form asks participants for name and school but does not
  require an account or login.
- Default/base evaluation questions are seeded automatically on first run
  and can be included/excluded or edited per activity from **Create
  Activity** — they are not edited globally from within the app yet.
