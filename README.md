# Vantix: FinTech Security Investigation Assistant (FSIA)

## About the project

### The problem

Security analysts who watch FinTech login and transaction logs face 83,450 events, and the few real
attacks are spread across many of them. Vantix narrows the events down to a short list of incidents an analyst can
review. On the synthetic dataset it scored 24,554 login and transaction events, flagged 1,072 and grouped them into
194 incidents (see Headline results).

### The approach

- **Hybrid detection.** A rule engine (`fsia_cyber/`, 9 rules with MITRE ATT&CK mapping) and an Isolation Forest model
  (`backend/ml/`) both flag suspicious events. The model's decisions are explained with SHAP. The flags are grouped
  into incidents with a severity, and each incident records which of the two detected it.
- **A local LLM, used for text only.** Ollama runs `llama3.2:3b` on the analyst's own machine. It writes the incident
  reports and answers free questions in the AI Copilot. It never decides what is an incident.
- **Analysts stay in the loop.** Every account has a role (analyst, manager or admin). Analysts can investigate and
  contain incidents; only a manager or admin can resolve one or assign it to someone else.

### How hallucination is controlled

A small local model can invent facts, so its output is checked by code and never trusted on its own:

1. **Grounding check.** Every IP address, user ID and amount in a generated report is checked against the incident's
   facts (the Copilot check also covers times, places and currency). Anything not found is listed and the text is
   marked unverified.
2. **Self-correction.** If the check fails, the model is asked again with the problems listed, and the best attempt wins.
3. **Verified template fallback.** If it still fails, a report written by code from the incident facts is used, and it
   goes through the same check. A report is stored only if it is grounded.
4. **Answered by code.** The Copilot's welcome summary is built from the data without the LLM. Questions about an
   incident's status, severity, type or risk are answered from the stored fields, not by the model.

### Tech stack

| Layer | Technology |
|---|---|
| API | Python 3.12, FastAPI, Uvicorn |
| Database and sign-in | Supabase (PostgreSQL and Supabase Auth) |
| Detection | Rule engine (`fsia_cyber/`), pandas, scikit-learn (Isolation Forest), SHAP |
| Local LLM | Ollama, `llama3.2:3b` |
| Frontend | React, Vite, TypeScript |

### Security

- Secrets (including the Supabase service-role key) live only in `backend/.env`, which is git-ignored. They are never
  in the frontend.
- The frontend never talks to the database: it only calls the FastAPI API. Row Level Security is on for every table,
  with no policies, so the public key can read and write nothing.
- Roles are enforced by the API on every request. A new account is always an analyst; the role cannot be set when
  registering. The sign-in token is kept in browser memory only.
- Rate limits: sign-in 5 per minute, registration 10 per minute, Copilot 10 questions per minute per user.
- The audit log records incident status and assignment changes and Copilot use (question length, never the question
  text).
- The interactive API docs (`/docs`) are turned off when `APP_ENV=production`.

## Architecture

```
data/*.csv ──► fsia_cyber/ (rules)  ─┐
          └──► backend/ml/ (Isolation Forest + SHAP) ─┴─► hybrid incidents
                 ──► Supabase, loaded and served by the FastAPI backend ──► React frontend
```

The frontend only talks to the FastAPI API, never to the database. Ollama runs locally and is called only through the
backend's AI bridge.

## Features by page

| Page | What it does |
|---|---|
| Login | Sign-in only; accounts are created by an admin via the API for now. |
| Dashboard | Counts, severity and type breakdowns for the current pipeline run. |
| Incidents | Search and filter by severity/status, paging, incident detail with timeline, "Why it was flagged" (SHAP and rule reasons) and AI analysis; Investigate / Contain / Resolve (manager/admin) status changes. |
| Reports | AI-generated, fact-checked reports for critical and high incidents; any incident's report can be generated on demand from its page. |
| AI Copilot | A welcome summary built from code; free questions answered by the LLM, grounded against incident data. |

Route details (including report generation) are in [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

## Headline results

Measured on the synthetic dataset; details in [docs/RESULTS.md](docs/RESULTS.md).

- 83,450 events ingested; 24,554 login/transaction events scored and 1,072 flagged (4.4%).
- 194 incidents (34 critical, 41 high, 119 medium, 0 low) linking 1,061 events.
- Hybrid detection caught 195/195 planted attacks with 0 false-positive incidents of 194 (Janvi's evaluation).
- 75/75 critical and high LLM reports verified; 8 used the verified template fallback.
- Pipeline 39.6 s and database load 42.3 s on an Apple M4 laptop.
- 356 backend tests pass.

Caveat: the data is synthetic and the rule thresholds were tuned while looking at the answer key, so detection figures
are optimistic.

## Folders

| Folder | What | Owner | Guide |
|---|---|---|---|
| `data/` | Synthetic dataset (Sept 2026) + answer key `ground_truth_*.csv` (evaluation only) | Aarushi | [data/README.md](data/README.md) |
| `fsia_cyber/` | Cybersecurity layer: 9 detection rules, alert correlation, MITRE ATT&CK mapping | Aarushi | [fsia_cyber/README.md](fsia_cyber/README.md) |
| `backend/ml/` | ML/LLM pipeline: preprocessing, anomaly detection, SHAP, hybrid incidents, reports, Copilot, evaluation | Janvi | [backend/ml/README.md](backend/ml/README.md) |
| `backend/` | FastAPI API, Supabase loading and integration | Anushka | [backend/README.md](backend/README.md) |
| `frontend/` | Vite + React app | Lakshayaa and Ayush (design), Anushka (API wiring) | |
| `docs/` | Results, API contract, labelled analyst-review sheets | | [docs/RESULTS.md](docs/RESULTS.md), [docs/API_CONTRACT.md](docs/API_CONTRACT.md) |

## Team setup (shared demo project)

This is the install path for a teammate. The team shares **one Supabase project that already holds the demo data**, so
you do **not** create a Supabase project, run any SQL, ingest data or run the pipeline. You install the tools, set up the
code, get the `backend/.env` file from Anushka privately, and register your own account. Every command is given for
macOS (and Linux) and for Windows PowerShell. Replace each `<PLACEHOLDER>` with your own value.

### 1. Prerequisites

You need Git, Python 3.12, Node 22 and Ollama. Ollama is only needed for Copilot questions and for generating new
reports; the dashboard, the incident list and existing reports work without it.

**macOS (Homebrew)**

```bash
brew install git python@3.12 node@22 ollama
brew link --overwrite node@22
```

Check:

```bash
git --version
python3.12 --version
node --version        # should print v22.x
ollama --version
```

**Windows (PowerShell)**

```powershell
winget install Git.Git
winget install Python.Python.3.12
winget install Ollama.Ollama
```

Node 22: install it from the v22 installer on [nodejs.org](https://nodejs.org) (the `winget` Node LTS package may be a
newer version). Close and reopen PowerShell after installing, then check:

```powershell
git --version
py -3.12 --version
node --version        # should print v22.x
ollama --version
```

`backend/ml/README.md` states Python 3.11 or newer is the minimum (pandas 3 does not install on 3.10); 3.12 is the
version this project was run with. `frontend/.mise.toml` pins Node 22. pnpm needs no install: the commands below run it
through `npx`.

### 2. Get the code

```bash
git clone https://github.com/janvishetty/miniproject.git
cd miniproject
```

The repository is private, so your GitHub account needs collaborator access first. The same two commands work in
PowerShell.

### 3. Backend and your `.env` file

The backend and the ML scripts use two separate Python environments on purpose (see section 4). This one holds the API
libraries.

**macOS / Linux** (from the repo root)

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows PowerShell** (from the repo root)

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
.venv\Scripts\pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

**Get `backend/.env` from Anushka, privately:** in person, or through a password manager's secure share. **Never**
through GitHub, chat, email or screenshots. Save it as `backend/.env` (on Windows make sure the editor does not add
`.txt` to the name). Do not create it from `.env.example`: that file is only a template with placeholders for a separate
Supabase project.

The file holds secrets and is git-ignored. These are the variables in it (names only):

| Variable | What it is |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY` | The shared project's address and keys. Do not edit. |
| `APP_ENV` | `development` locally (turns on `/docs`). |
| `CORS_ORIGINS` | Exact frontend origins. Must include `http://localhost:8443`; `http://127.0.0.1:8443` is recommended too. `*` is rejected. |
| `AUTO_CONFIRM_EMAIL` | `true` in development so new accounts can sign in straight away. |
| `ML_PYTHON` | **Full path of your own ML environment's Python (section 4).** If the file you received has a path from another machine, change it. |
| `DATA_DIR`, `ML_OUTPUT_DIR`, `ML_STEP_TIMEOUT_SECONDS` | Optional; leave as they are. |

The app refuses to start if a required value is missing; the message names the variable, never its value.

### 4. ML environment

**Why two Python environments?** The API (FastAPI, Supabase client) and the ML scripts (pandas, NumPy, scikit-learn,
SHAP) need different libraries, and the ML requirements are pinned to exact versions. Keeping them apart stops one set
from breaking the other. The API runs Copilot and report generation with the interpreter named in `ML_PYTHON`.

This environment lives in the repo root.

**macOS / Linux** (from the repo root; if your shell is still inside `backend/`, run `cd ..` first)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/ml/requirements.txt
```

**Windows PowerShell** (from the repo root; if you are still inside `backend`, run `cd ..` first)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r backend\ml\requirements.txt
```

Then set `ML_PYTHON` in `backend/.env` to that interpreter's **full path**. A bare name such as `python3` is refused.
`<REPO>` is the full path of the cloned folder:

```text
macOS / Linux:      ML_PYTHON=<REPO>/.venv/bin/python3
Windows PowerShell: ML_PYTHON=<REPO>\.venv\Scripts\python.exe
```

### 5. Frontend

The same command in both shells:

```bash
cd frontend
npx pnpm@10.34.3 install
```

### 6. Ollama (optional: Copilot and new reports)

Ollama was installed in section 1. Start it and download the model (about 2 GB, once):

**macOS / Linux**

```bash
ollama serve                 # skip if the Ollama app is already running
ollama pull llama3.2:3b      # in a second terminal if serve is running in the first
```

**Windows PowerShell**

```powershell
ollama serve                 # skip if Ollama is already running in the system tray
ollama pull llama3.2:3b      # in a second window if serve is running in the first
```

### 7. Your own account

Each teammate registers their **own** account. Never share a password or use someone else's account.

1. Start the API (see section 8) and open **`http://127.0.0.1:8000/docs`** (available when `APP_ENV=development`).
2. Click `POST /auth/register`, then **Try it out**, fill in the body and click **Execute**: `name`, `username`,
   `email`, `password` (8 to 128 characters) and `position`, which must be one of `Security Analyst`, `Senior Analyst`,
   `SOC Manager`, `Threat Intelligence Lead`, `Compliance Officer`, `Platform Engineer`, `CISO / CTO`.
3. The account starts as **analyst**: it can investigate and contain incidents but not resolve them. If you need
   more, ask Anushka to promote it. **Admin only**, in the Supabase SQL Editor (use `'manager'` for a manager):
   ```sql
   update public.profiles set role = 'admin' where email = '<EMAIL>';
   ```
4. Sign in at `http://localhost:8443` with your own email and password.

### 8. Daily run

Three terminals (or PowerShell windows), started in this order. The Ollama one is optional (section 6).

**macOS / Linux**

```bash
# Terminal 1: the local LLM (optional; skip if the Ollama app is running)
ollama serve

# Terminal 2: the API on port 8000
cd backend
source .venv/bin/activate
uvicorn app.main:app --port 8000

# Terminal 3: the frontend on port 8443
cd frontend
npx pnpm@10.34.3 dev
```

**Windows PowerShell**

```powershell
# Window 1: the local LLM (optional; skip if Ollama is running in the system tray)
ollama serve

# Window 2: the API on port 8000
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --port 8000

# Window 3: the frontend on port 8443
cd frontend
npx pnpm@10.34.3 dev
```

Open `http://localhost:8443` and sign in. The API docs are at `http://127.0.0.1:8000/docs` (development only).

### 9. Shared data: read before the demo

Everyone uses the **same database**. A status change (Investigate, Contain, Resolve) and a generated report are visible
to all teammates immediately. Do not run the pipeline, the data ingestion or `demo_reset.py` unless you are the admin.
**Before the demo, the admin runs `demo_reset.py`** (section 10).

### 10. Demo reset (admin only)

[backend/scripts/demo_reset.py](backend/scripts/demo_reset.py) puts incident statuses back to a known demo state through
the running API. Run it from `backend/` with the API running, and look at the plan first. The script itself needs an
admin or manager account (analysts cannot set `RESOLVED`).

**macOS / Linux**

```bash
cd backend
python3.12 scripts/demo_reset.py --dry-run     # prints the plan, changes nothing
python3.12 scripts/demo_reset.py               # asks for email and password, then asks you to type "yes"
```

**Windows PowerShell**

```powershell
cd backend
py -3.12 scripts\demo_reset.py --dry-run
py -3.12 scripts\demo_reset.py
```

Every non-open incident goes back to `OPEN`, then the demo states set at the top of the script are applied. See
[backend/README.md](backend/README.md) section 13.

### 11. Troubleshooting

| Problem | Fix |
|---|---|
| `address already in use` (API) or `Port 8443 is already in use` (frontend) | A server is already running, probably in another terminal tab. Stop it, or use the one that is running. |
| `401` | The login token expired or is missing: sign in again (and re-authorize on the docs page). |
| `503` "AI service unavailable" | Start `ollama serve` and check `llama3.2:3b` is pulled. Also check `ML_PYTHON` is a full path to your own ML environment's Python. |
| Browser CORS errors | `CORS_ORIGINS` in `backend/.env` must contain the exact frontend origin (`http://localhost:8443`). Restart the API after changing it. |
| `409` "no pipeline run loaded yet" | The shared project should already have a run: tell the admin. Do not load one yourself. |
| Startup says `Invalid or missing configuration` | `backend/.env` is missing, in the wrong folder, or a value is empty; the message names the variable. |

More cases are in [backend/README.md](backend/README.md) section 11.

### 12. Security notes

- Never commit `backend/.env` (it is git-ignored). Never paste the service-role key anywhere: it gives full database
  access.
- The frontend never needs any Supabase key; it only talks to the API.
- Share `.env` only privately (in person or a password manager's secure share).
- Rotate the Supabase keys in the Supabase dashboard after the project ends.

### 13. Limitations

From [docs/RESULTS.md](docs/RESULTS.md):

- The data is synthetic.
- Rule thresholds were tuned while looking at the answer key, so detection figures are optimistic.
- Correlation is entity-based (user, IP, time), not graph-based.
- The small LLM can mis-relate facts; the grounding check and the template fallback contain this.
- Analyst status changes belong to one pipeline run.
- There is no response-time data (the dashboard shows "—").

### 14. Future scope

- An attack graph for each incident
- Real-time event streaming
- Public deployment (Docker)
- More data sources
- Conversation memory in the Copilot

### 15. Setting up a separate Supabase project (not needed for the team demo)

Only the admin needs this, to build a fresh copy from scratch. Create a free project at
[supabase.com](https://supabase.com), then:

1. **Database.** In **Supabase Dashboard → SQL Editor → New query**, paste a file and click **Run**, in this order:
   [backend/sql/schema.sql](backend/sql/schema.sql), then
   [backend/sql/migrations/002_ml_fields.sql](backend/sql/migrations/002_ml_fields.sql), then
   [backend/sql/migrations/004_set_current_run.sql](backend/sql/migrations/004_set_current_run.sql). The "already
   applied, do not run again" note inside 002 refers only to the original team database. There is no 001 or 003.
   [backend/sql/verify_schema.sql](backend/sql/verify_schema.sql) is an optional read-only check and may be outdated: it
   predates migration 002.
2. **Email confirmation.** For development turn it off: **Authentication → Providers → Email → Confirm email = off**.
3. **`backend/.env`.** Copy the template (`cp .env.example .env` on macOS/Linux, `Copy-Item .env.example .env` in
   PowerShell, from `backend/`) and fill in the three Supabase values from **Project Settings → API**, plus
   `CORS_ORIGINS` (including `http://localhost:8443`) and `ML_PYTHON`. Each Supabase project has its own accounts and
   data. A new project starts empty: register your own account there and promote it to admin (below). Accounts from
   another project will not work. Never share the service-role key publicly; it gives full database access.
4. **First run**, with the API running, on `http://127.0.0.1:8000/docs`. For each route click it, then **Try it out**,
   fill the fields and click **Execute**:
   1. Register (`POST /auth/register`) and promote the account to admin with the SQL in section 7.
   2. Log in (`POST /auth/login`), copy the `access_token`, click **Authorize** and paste it.
   3. Ingest: `POST /admin/ingest/all` (try `dry_run` = `true` first), then poll `GET /admin/ingest/jobs/{job_id}` until
      `completed`.
   4. Pipeline: `POST /admin/pipeline/run` (needs `ML_PYTHON`; about 40 s for the scripts and 42 s for the load on an
      Apple M4), poll `GET /admin/pipeline/jobs/{job_id}`, then check `GET /admin/pipeline/runs` for a `completed` run
      with `is_current` true. If the ML output files already exist, `POST /admin/pipeline/load-existing` loads them
      instead. Only one ingestion or pipeline job runs at a time.
   5. Optional reports (needs Ollama; about 12 s per report, 75 critical and high incidents): run `summarize.py` from
      the repo root, then `POST /admin/pipeline/load-existing` with `force` = `true`. A forced reload keeps incident
      status and analyst.

      macOS / Linux: `.venv/bin/python3 backend/ml/summarize.py`
      Windows PowerShell: `.venv\Scripts\python.exe backend\ml\summarize.py`

   Optional on macOS / Linux: the same calls work with `curl`. In Windows PowerShell `curl` is an alias for a different
   command, so type `curl.exe`, or use the docs page. Full details, dry runs and checks are in
   [backend/README.md](backend/README.md) sections 7 and 8.

#### Running the ML scripts by hand (optional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/ml/requirements.txt
python3 backend/ml/preprocess.py
python3 backend/ml/features.py
python3 backend/ml/model.py
python3 backend/ml/incidents.py        # runs the fsia_cyber rules too (hybrid)
python3 backend/ml/summarize.py        # needs Ollama + llama3.2:3b
python3 backend/ml/frontend_data.py
python3 backend/ml/evaluate.py
```

Rules on their own: `python3 fsia_cyber/run.py`.

## Team

| Person | Area |
|---|---|
| Janvi | ML and LLM pipeline |
| Aarushi | Rule engine and dataset |
| Anushka | Backend, API and integration |
| Lakshayaa and Ayush | Frontend design |
