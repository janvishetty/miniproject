# FSIA / CirionSOC backend (FastAPI)

The API server for the FSIA / CirionSOC project. It is built with **FastAPI** and uses **Supabase** (PostgreSQL + Supabase Auth). The frontend talks only to this API, never to the database directly.

This document covers only what exists in the code today.

## Status

| Step | Scope | Status |
|------|-------|--------|
| 1 | Foundation and auth: config, Supabase clients, error format, logging, security headers, rate limiting, register / login / me / logout, roles, audit log, database schema | **Done** |
| 2 | CSV ingestion (`data/` → `raw_events`, `events`, reference tables): admin-only routes, dry run, background jobs, audit summary | **Done** |
| 3 | ML pipeline integration (`backend/ml/output/` → `pipeline_runs`, `ml_results`, `incidents`, `incident_events`, `rule_alerts`, `reports`, `dashboard_snapshots`): admin-only run / load routes. Verified on real data on 18 Oct 2026 (see **Step 3 verified results**) | **Done** |
| 4 | Dashboard, report and Copilot APIs | Planned |
| 5 | Hardening and deployment (pinned versions, trusted proxy headers, production config) | Planned |

## Requirements

- Python **3.11+**
- A **Supabase** project (free tier is fine)

## 1. Database setup (Supabase)

Do this once per Supabase project.

1. Open **Supabase Dashboard → SQL Editor → New query**, paste the contents of [sql/schema.sql](sql/schema.sql) and click **Run**.
   - It is safe to re-run: every statement uses `IF NOT EXISTS` / `OR REPLACE`.
   - It creates 13 tables (reference data, events, pipeline runs, AI results, `profiles`, `audit_log`) and turns Row Level Security on for all of them.
2. In a new query, run [sql/verify_schema.sql](sql/verify_schema.sql). It is read-only. Expected results:
   - Query 1: 13 rows, `rls_enabled = true` on every row.
   - Query 2: 0 rows (no RLS policies).
   - Query 3: the `profiles` unique-username and role-check constraints.
3. For development, turn off email confirmation: **Authentication → Providers → Email → Confirm email = off**. Together with `AUTO_CONFIRM_EMAIL=true` (see below), new accounts can log in straight away.

## 2. Configuration (`backend/.env`)

Settings are read from `backend/.env` (found by absolute path, so it works from any folder). Environment variables override the file.

Create the file from the template, from inside `backend/`:

```bash
# macOS / Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Then open `backend/.env` and fill in your own values. The Supabase values are under **Supabase Dashboard → Project Settings → API**.

| Variable | Required | Purpose |
|----------|----------|---------|
| `SUPABASE_URL` | Yes | Bare project URL (`https://<project>.supabase.co`). No path such as `/rest/v1` and no query string. A trailing `/` is removed. |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | **Secret.** Server-side key used for all database reads/writes and for creating/deleting auth users. Bypasses RLS. Never put it in the frontend. |
| `SUPABASE_ANON_KEY` | Yes | Public key, used only for the email + password sign-in call and for checking tokens. |
| `APP_ENV` | No (default `development`) | `development`, `production` or `test`. `production` turns off `/docs`, `/redoc` and `/openapi.json`. |
| `CORS_ORIGINS` | No (default `http://localhost:5173`) | Comma-separated list of exact frontend origins. `*` is rejected. |
| `AUTO_CONFIRM_EMAIL` | No (default `true`) | `true` = new accounts are confirmed immediately. `false` = Supabase must confirm the email before the user can log in. |
| `DATA_DIR` | No (default `../data`) | Folder the ingestion routes read the five allowed CSV files from (see **Loading the data**). Used since Step 2. |
| `ML_OUTPUT_DIR` | No (default `backend/ml/output`) | Folder the pipeline routes read the ML module's generated files from (see **Loading the ML output**). |
| `ML_PYTHON` | For `/admin/pipeline/run` | Python used to run the ML scripts. **Must be an absolute path to an existing executable** (for example `<REPO>/.venv/bin/python3`). The default `python3` is refused. Not needed for `load-existing`. |
| `ML_STEP_TIMEOUT_SECONDS` | No (default `600`, allowed 10–3600) | Time allowed for each ML script before it is stopped. |

The app checks the configuration at startup and refuses to start if a required value is missing, empty or still a placeholder (for example `PASTE_YOUR_...`). The error names the variable and the problem, never the value.

## 3. Install and run

All commands run from the `backend/` folder.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs on `http://127.0.0.1:8000`. In development, interactive docs are at `/docs` and `/redoc`.

Quick check:

- `GET /health` → `{"status": "ok"}` (server is up)
- `GET /health/db` → `{"status": "ok"}` (server can reach Supabase)

`backend/requirements.txt` is for the API only. Janvi's ML module has its own `backend/ml/requirements.txt`; do not merge them.

## 4. Tests

From `backend/`, with the virtual environment active:

```bash
pytest
```

[pytest.ini](pytest.ini) sets the import path and the `tests/` folder, so no extra flags are needed. Use `pytest -v` to see every test name.

The full suite is **185 tests** (from the last full run).

The tests never touch your real Supabase project, never read the real `data/` folder and never read the real `backend/ml/output/`. [tests/conftest.py](tests/conftest.py) sets fake environment variables before the app is imported and replaces the Supabase clients with an in-memory fake (it supports select with filters, ordering, paging and counts, insert, update, upsert, `rpc`, unique-key rules and simulated outages). Rate limiting is off during tests, except in the test that checks it.

| File | What it covers |
|------|----------------|
| [tests/test_config.py](tests/test_config.py) | Settings validation: missing / placeholder values, URL format, wildcard CORS, secrets kept out of errors and `repr` |
| [tests/test_auth.py](tests/test_auth.py) | Health checks, security headers, error format, register, login, rate limit, `/auth/me`, roles, logout, audit log contents, docs turned off in production |
| [tests/test_auth_hardening.py](tests/test_auth_hardening.py) | `401` / `403` / `503` mapping for token and profile lookups (including Supabase `429` and `5xx`), no tokens or exception messages in logs, per-table counts in the ingestion audit entry |
| [tests/test_normalize.py](tests/test_normalize.py) | CSV parsing and mapping: timestamps, blanks, Y/N, BOM, CRLF, rejected-row reporting, the file allowlist |
| [tests/test_ingestion.py](tests/test_ingestion.py) | Ingestion routes: authorization (401 / 403 / 200), dry run, one job at a time (409), idempotent rerun, retry with backoff, summary, audit entry without row data |
| [tests/test_ml_loader.py](tests/test_ml_loader.py) | Parsing of the ML output (`is_flagged` used, `"None"` → NULL, severity lowercase, stale reports), consistency checks, `dry_parse`, and the load against the fake database: already loaded, `force`, count mismatch, missing `set_current_run`, unknown event ids |
| [tests/test_ml_adapter.py](tests/test_ml_adapter.py) | Script allowlist, absolute interpreter only, clean child environment (no `SUPABASE_*`), stdout discarded, timeout, stop at first failure (tiny fake scripts only) |
| [tests/test_pipeline_routes.py](tests/test_pipeline_routes.py) | `/admin/pipeline/*`: 401 / 403 (analyst, manager) / 2xx for every route, 409s, dry runs, failed runs, audit entries |

The ingestion tests read the small CSV files in [tests/fixtures/data/](tests/fixtures/data/); the pipeline tests read the synthetic files in [tests/fixtures/ml_output/](tests/fixtures/ml_output/).

## 5. API routes

| Method | Path | Access | Rate limit | Description |
|--------|------|--------|------------|-------------|
| GET | `/health` | Public | – | Liveness check. Does not touch the database. |
| GET | `/health/db` | Public | – | Checks the server can reach Supabase. Returns `ok` or `503 unavailable`, with no details. |
| POST | `/auth/register` | Public | 10/minute per IP | Creates a Supabase Auth user and a `profiles` row. Body: `name`, `username`, `email`, `password`, `position`. Role is always `analyst`. Returns `201`. |
| POST | `/auth/login` | Public | 5/minute per IP | Email + password sign-in. Returns `access_token`, `token_type`, `expires_in` and the profile. |
| GET | `/auth/me` | Any logged-in user | – | Returns the current user's profile. |
| POST | `/auth/logout` | Any logged-in user | – | Ends the Supabase session (best effort). The client should also discard its token. |
| GET | `/admin/ping` | `admin` only | – | Tests role-based access. Returns `{"status": "ok", "role": "admin"}`. |
| POST | `/admin/ingest/reference?dry_run=false` | `admin` only | – | Starts a background job that loads `users_devices.csv` → `user_devices` and `threat_indicators.csv` → `threat_indicators`. |
| POST | `/admin/ingest/events?source=all&dry_run=false` | `admin` only | – | Starts a background job that loads event CSVs into `raw_events`, then `events`. `source` is `auth`, `api`, `transaction` or `all` (default `all`); anything else returns `422`. |
| POST | `/admin/ingest/all?dry_run=false` | `admin` only | – | Starts a background job that loads everything, in this order: reference tables, then `raw_events`, then `events`. |
| GET | `/admin/ingest/jobs/{job_id}` | `admin` only | – | Status and report of a job. `404` if the id is unknown (including after a server restart). |
| GET | `/admin/ingest/summary` | `admin` only | – | CSV row counts next to the database row counts for `user_devices`, `threat_indicators`, `raw_events` and `events`. |
| POST | `/admin/pipeline/run?force=false&dry_run=false` | `admin` only | – | Starts a background job: runs the five ML scripts in order, then loads their output. With `dry_run=true` the scripts still run (they rewrite `backend/ml/output/`), but the output is only parsed and checked, not loaded. |
| POST | `/admin/pipeline/load-existing?force=false&dry_run=false` | `admin` only | – | Starts a background job that loads the files already in `ML_OUTPUT_DIR`. With `dry_run=true` it only parses and checks them. Missing files return `409` "run the pipeline first"; files from different runs return `409` with the reason. |
| GET | `/admin/pipeline/runs?limit=20&offset=0` | `admin` only | – | Pipeline runs, newest first (`limit` 1–100). Returns `items`, `total`, `limit`, `offset`. |
| GET | `/admin/pipeline/runs/{id}` | `admin` only | – | One run. `422` if `id` is not a uuid, `404` if unknown. |
| GET | `/admin/pipeline/jobs/{job_id}` | `admin` only | – | Status and report of a pipeline job (`404` for unknown ids and for ingestion jobs). |
| GET | `/docs`, `/redoc`, `/openapi.json` | Public, development only | – | API docs. Return `404` when `APP_ENV=production`. |

Logged-in routes need the header `Authorization: Bearer <access_token>`.

Input rules for `/auth/register`:

- `username`: 3–30 characters, letters, digits, `_`, `.` and `-`. Stored in lower case.
- `email`: stored in lower case. Login is not case-sensitive for email.
- `password`: 8–128 characters.
- `position`: one of `Security Analyst`, `Senior Analyst`, `SOC Manager`, `Threat Intelligence Lead`, `Compliance Officer`, `Platform Engineer`, `CISO / CTO` (must match the frontend's login form).
- Unknown fields, including `role`, are ignored.

Status codes: `401` = missing, malformed, invalid or expired token. `403` = valid user without permission, or no profile row. `409` = username or email already taken, another ingestion or pipeline job is already running, or the ML output is missing / inconsistent. `422` = invalid input. `429` = this API's own rate limit reached. `503` = Supabase unavailable.

**Supabase problems return `503`, not `401`.** If Supabase cannot be reached, answers with a server error (`5xx`), or rate-limits the request (`429`) while the server checks a token, looks up the profile (`/auth/me` and every protected route) or signs a user in, the API returns `503 "Service temporarily unavailable"` (login returns `503 "Authentication service unavailable"`). Only a token that Supabase itself rejects with a `4xx` answer gives `401`. Clients can retry a `503` after a moment.

## 6. Roles

Every account has one role in `profiles.role`:

| Role | Who | Notes |
|------|-----|-------|
| `analyst` | Everyone who registers | Default. The public API can never set any other role. |
| `manager` | Promoted by an admin | Exists in the schema; no route needs it yet. |
| `admin` | Promoted by an admin | Can call `/admin/ping`, all `/admin/ingest/...` routes and all `/admin/pipeline/...` routes. |

**Promote a user to admin.** Run this in **Supabase → SQL Editor**, with the user's own email:

```sql
update public.profiles set role = 'admin' where email = 'you@example.com';

-- check
select id, username, email, role from public.profiles;
```

Use `'manager'` the same way. The role is read from the database on every request, so the change applies immediately; the user does not need to log in again.

## 7. Loading the data (CSV ingestion)

The ingestion routes copy the project's CSV files into Supabase. All of them need the `admin` role.

**Allowed files.** Only these five exact filenames are ever read, from the folder set by `DATA_DIR`:

| File | Goes to |
|------|---------|
| `users_devices.csv` | `user_devices` (key: `user_id` + `device_id`) |
| `threat_indicators.csv` | `threat_indicators` (key: `ip_address`) |
| `authentication_logs.csv` | `raw_events` and `events` (`source_type` `auth`; `event_kind` is `login` or `logout`) |
| `api_logs.csv` | `raw_events` and `events` (`source_type` `api`; `event_kind` `api_call`) |
| `transactions.csv` | `raw_events` and `events` (`source_type` `transaction`; `event_kind` `transaction`) |

`ground_truth_*.csv` and `data/README.md` are **never** opened, listed or ingested, and neither is any other file. The code builds file paths only from this fixed list, and no request parameter can supply a filename (`source` accepts only `auth`, `api`, `transaction` or `all`). A test checks that any other name is rejected.

**How a job behaves**

- Each `POST` returns at once with a job record (`job_id`, `status: "running"`). The work runs in the background; poll `GET /admin/ingest/jobs/{job_id}` until `status` is `completed` or `failed`. Job records are kept in memory only, so they are lost when the server restarts.
- **Only one job runs at a time, across ingestion and the pipeline.** Starting another while one is running returns `409 Conflict` (`"Another ingestion or pipeline job is already running"`). Wait for the first to finish, then try again.
- **`dry_run=true`** parses and validates every row but writes nothing. The report shows `rows_read`, the rejected rows, and `rows_written: 0`; rows that would be written = `rows_read` minus `rejected_count`. `dry_run=false` (the default) writes to the database.
- **Order.** `/admin/ingest/all` runs reference tables, then `raw_events`, then `events`.
- **Safe to rerun.** Rows are written in chunks of 1000 with an upsert on the table's key (`user_id,device_id` / `ip_address` / `source_type,source_event_id` / `event_id`), so running the same load again never creates duplicates. Original ids (`E…`, `A…`, `T…`) are kept.
- **Retries.** A failed write is retried up to 4 times with a growing delay (0.5 s, then doubling). If it still fails, the job ends with `status: "failed"` and a generic error message.
- **Bad rows never stop a load.** A row that fails validation (for example a bad timestamp) is skipped and listed under `rejected_samples` with its file, line number (the header is line 1), id and reason. The first 20 are shown; `rejected_count` has the total. `raw_events` keeps an untouched copy of every row that has an id, even rows that `events` rejects.
- **Conversions.** Blank values become `NULL`; timestamps (`YYYY-MM-DD HH:MM:SS`) are stored as UTC; `registered_device` `Y`/`N` becomes a boolean; `mfa_status` is kept exactly, including `n/a`; for `api_logs.csv` the `status` column stays `NULL` (the file has only a numeric `status_code`).
- **Report.** `report.tables` lists, per table, `rows_read`, `rows_written`, `rejected_count`, `rejected_samples` and `duration_seconds`; the report also has totals. Because `raw_events` and `events` are separate passes over the same files, a file's rows are counted once per table.
- **`GET /admin/ingest/summary`** compares CSV row counts with the database counts per table. For the project's current CSV files the expected counts are `user_devices` 1031, `threat_indicators` 300, `raw_events` 83450 and `events` 83450 (minus any rejected rows).

### How to load the data

Replace every `<PLACEHOLDER>` with your own value. Never commit real credentials or tokens, and never paste them into chat or a shared terminal.

1. **Register an account** (it starts as `analyst`):

   ```bash
   curl -s -X POST http://127.0.0.1:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{"name": "<YOUR_NAME>", "username": "<USERNAME>", "email": "<YOUR_EMAIL>", "password": "<YOUR_PASSWORD>", "position": "SOC Manager"}'
   ```

2. **Promote it to admin** in **Supabase → SQL Editor** (see **Roles**):

   ```sql
   update public.profiles set role = 'admin' where email = '<YOUR_EMAIL>';
   ```

3. **Log in and keep the access token** in a shell variable:

   ```bash
   curl -s -X POST http://127.0.0.1:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "<YOUR_EMAIL>", "password": "<YOUR_PASSWORD>"}'
   # copy "access_token" from the response, then:
   export TOKEN='<ACCESS_TOKEN>'
   ```

4. **Dry run.** Start it, then poll with the `job_id` from the response until `status` is `completed`. Check the counts and any rejected rows:

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/admin/ingest/all?dry_run=true" -H "Authorization: Bearer $TOKEN"
   curl -s http://127.0.0.1:8000/admin/ingest/jobs/<JOB_ID> -H "Authorization: Bearer $TOKEN"
   ```

5. **Real load**, only if the dry run looks right. Same pattern, with `dry_run=false`:

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/admin/ingest/all?dry_run=false" -H "Authorization: Bearer $TOKEN"
   curl -s http://127.0.0.1:8000/admin/ingest/jobs/<JOB_ID> -H "Authorization: Bearer $TOKEN"
   ```

6. **Check the result:**

   ```bash
   curl -s http://127.0.0.1:8000/admin/ingest/summary -H "Authorization: Bearer $TOKEN"
   ```

If a poll returns `503`, Supabase was briefly unreachable. The job itself keeps running; poll again.

## 8. Loading the ML output (pipeline)

The pipeline routes load Janvi's generated files into Supabase as one **pipeline run**. All of them need the `admin` role and share the one-job lock with ingestion.

**Before the first load**

1. Load the CSV data first (section 7): `ml_results`, `incident_events` and `rule_alerts` point at `events` rows.
2. Run [sql/migrations/004_set_current_run.sql](sql/migrations/004_set_current_run.sql) **once** in **Supabase → SQL Editor** (migration 002 must already be applied). It creates `set_current_run(run_id)`, the only thing that switches which run is current. If it is missing, a load fails with `set_current_run missing: run migration 004`.
3. For `/admin/pipeline/run`, set `ML_PYTHON` in `backend/.env` to an absolute path (see **Configuration**).

**Generated files.** `backend/ml/output/` (and `data/processed/`) are produced by the ML scripts. They are git-ignored: never commit them, never edit or delete them by hand, and never use `git add -f`. The API only reads them. `POST /admin/pipeline/run` regenerates them (it overwrites the previous output). Only these files are ever read: `scored_auth.csv`, `scored_txn.csv`, `incidents.json`, `dashboard.json`, `pipeline_run.json`, `rule_alerts.csv` (required) and `reports.json` (optional; it needs Ollama and may not exist, in which case no reports are loaded).

**What the run script step does.** `/admin/pipeline/run` runs `preprocess.py`, `features.py`, `model.py`, `incidents.py`, `frontend_data.py` in that order and stops at the first failure (the job reports the step name, exit code and the last 20 stderr lines, each cut to 200 characters). It never runs `summarize.py`, `copilot.py`, `evaluate.py`, `inject_test.py`, `review_sheet.py` or `export_samples.py`.

**What a load does**

- **Consistency first.** The same `pipeline_run_id` must be in `pipeline_run.json`, every incident and `dashboard.json`; otherwise the load stops with `409` and nothing is written.
- **One run, fingerprinted.** Our own uuid identifies the run; Janvi's 12-character `pipeline_run_id` is stored as `pipeline_runs.source_fingerprint`, and the file's `created_at` goes into `notes` as `source_created_at=<value>`. If a **completed** run with the same fingerprint exists, the result is `already_loaded` and nothing is written. `force=true` instead re-upserts the data into that same run (no second run row; it does not change which run is current).
- **Order.** `pipeline_runs` (status `running`) → `ml_results` (chunks of 1000) → `incidents` (chunks of 500) → `incident_events` → `rule_alerts` → `reports` → `dashboard_snapshots`. Then the row counts are verified, the run is marked `completed`, and `set_current_run` makes it current. If anything fails, the run is marked `failed` with `error_message` = exception type and step (no values), and the previous current run stays current. (A failed `force` reload is the one exception: it re-upserts identical data into an already completed run, so that run keeps its `completed` status and the job just fails.)
- **Conversions and skips.** `is_flagged` (`1`/`0`) becomes `ml_results.is_anomalous`; `is_anomaly` is ignored; any other value is skipped and counted. An empty `flag_reason` becomes NULL. Severity is stored lowercase (`critical`, `high`, `medium`, `low`); other values are skipped. Naive timestamps are treated as UTC. `ip_threat_level` `"None"` becomes NULL (the original object, including its own `pipeline_run_id` key, is kept in `incidents.raw`). Rows with unparsable numbers are skipped. Event ids that are not in `events` are skipped and counted for `ml_results`, `incident_events` and `rule_alerts`. The report lists skip counts per table under `skip_reasons`.
- **Reports.** Only reports whose `pipeline_run_id` equals the run's fingerprint are loaded; older ones are skipped and counted as `stale_reports`.
- **`rule_alerts` is global.** It has no run column and is unique on (`event_id`, `rule_id`). Each load upserts all alerts, including the context-only ones (`R_IMPOSSIBLE_TRAVEL_CANDIDATE`, `R_NEW_BENEFICIARY`), and nothing is ever deleted, so alerts from older runs stay.
- **Retries.** Upserts are retried like ingestion (4 attempts). The `pipeline_runs` insert and the `set_current_run` call are never retried.

### How to load the ML output

Replace every `<PLACEHOLDER>`. Use the admin token from the data-loading steps above.

1. **Check first (no database writes):**

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/admin/pipeline/load-existing?dry_run=true" -H "Authorization: Bearer $TOKEN"
   curl -s http://127.0.0.1:8000/admin/pipeline/jobs/<JOB_ID> -H "Authorization: Bearer $TOKEN"
   ```

   The report shows the fingerprint, per-table counts, skips and consistency checks.
2. **Load:**

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/admin/pipeline/load-existing" -H "Authorization: Bearer $TOKEN"
   ```

   Poll the job as above until `status` is `completed`. Use `POST /admin/pipeline/run` instead if the files need to be regenerated first.
3. **Check the run:** `GET /admin/pipeline/runs` (the newest run should be `completed` with `is_current: true`).

### How to load (what I actually did)

This is the sequence used for the first real load on 18 Oct 2026. Replace `<REPO>` and `<PLACEHOLDER>`; never put real credentials or tokens in this file.

1. **Run Janvi's scripts by hand**, from the repo root, with the repo-root virtual environment (`<REPO>/.venv`). Ollama is not needed for these five:

   ```bash
   cd <REPO>
   .venv/bin/python3 backend/ml/preprocess.py
   .venv/bin/python3 backend/ml/features.py
   .venv/bin/python3 backend/ml/model.py
   .venv/bin/python3 backend/ml/incidents.py
   .venv/bin/python3 backend/ml/frontend_data.py
   ```

   (`summarize.py`, which writes `reports.json`, needs Ollama and was not run.)
2. **Dry run of the load** (no database writes), then poll the job until `status` is `completed`:

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/admin/pipeline/load-existing?dry_run=true" -H "Authorization: Bearer $TOKEN"
   curl -s http://127.0.0.1:8000/admin/pipeline/jobs/<JOB_ID> -H "Authorization: Bearer $TOKEN"
   ```
3. **The real load**, same pattern without `dry_run`:

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/admin/pipeline/load-existing" -H "Authorization: Bearer $TOKEN"
   curl -s http://127.0.0.1:8000/admin/pipeline/jobs/<JOB_ID> -H "Authorization: Bearer $TOKEN"
   ```
4. **Check the result** in **Supabase → SQL Editor** (read-only; counts for the current run):

   ```sql
   select id, status, is_current, source_fingerprint, events_scored, incident_count
   from public.pipeline_runs where is_current;

   with cur as (select id from public.pipeline_runs where is_current),
        inc as (select id from public.incidents where pipeline_run_id in (select id from cur))
   select 'ml_results' as tbl, count(*) from public.ml_results where pipeline_run_id in (select id from cur)
   union all select 'ml_results flagged', count(*) from public.ml_results
             where is_anomalous and pipeline_run_id in (select id from cur)
   union all select 'incidents', count(*) from inc
   union all select 'incident_events', count(*) from public.incident_events where incident_id in (select id from inc)
   union all select 'reports', count(*) from public.reports where incident_id in (select id from inc)
   union all select 'dashboard_snapshots', count(*) from public.dashboard_snapshots where pipeline_run_id in (select id from cur)
   union all select 'rule_alerts (global)', count(*) from public.rule_alerts;
   ```

### Step 3 verified results

Measured on the real data on 18 Oct 2026 (nothing here is an estimate):

| Item | Result |
|------|--------|
| Pipeline run by hand | 39.6 s (5 scripts; Ollama not needed) |
| `load-existing` | 42.3 s, 27,878 rows written, 0 rejected |
| `pipeline_runs` | 1 (`completed`, `is_current`, fingerprint `0087b9cf856d`) |
| `ml_results` | 24,554 (1,072 `is_flagged` = 952 logins + 120 transfers) |
| `incidents` | 194 (34 critical / 41 high / 119 medium / 0 low), all `detected_by` = `ml+rules` |
| `incident_events` | 1,061 |
| `rule_alerts` | 2,067 |
| `dashboard_snapshots` | 1 |
| `reports` | 0 (Ollama has not been run yet, so there is no `reports.json`) |
| Second `load-existing` | `already_loaded`, nothing written |
| Migrations | 002 and 004 applied in Supabase |

### Cleaning up failed runs (you run this, not the API)

The API never deletes anything. A failed run leaves a `failed` row in `pipeline_runs` plus whatever it had written; it never blocks a new load. To remove them, run this yourself in **Supabase → SQL Editor**. Review the first query before running the second.

```sql
-- 1. look first
select id, status, is_current, started_at, error_message
from public.pipeline_runs
where status in ('failed', 'running')
order by started_at desc;

-- 2. delete failed runs only (never a completed or current run).
--    Cascades to ml_results, incidents, incident_events, reports, dashboard_snapshots.
--    rule_alerts is global and is not touched.
delete from public.pipeline_runs
where status = 'failed' and not is_current;
```

A `running` row that never finished (for example the server stopped mid-load) is not deleted by this; look at it in query 1 first.

## 9. Security notes

- **Secrets.** `backend/.env` is ignored by git (root `.gitignore` ignores `.env` and `.env.*` and keeps only `.env.example`). Never commit it and never put the service role key in the frontend.
- **Row Level Security** is on for every table, with **no policies**. The public anon key can read and write nothing. Only this server, using the service role key, can access the data.
- **Roles are decided on the server.** Registration always stores `analyst`; promotion happens only in the SQL Editor.
- **One error format** for every error:

  ```json
  {"error": {"code": "validation_error", "message": "Request validation failed", "details": [{"field": "password", "message": "..."}]}}
  ```

  Errors never contain stack traces, SQL or the values the user sent (a rejected password is never echoed back). Unexpected errors return `500` with `"Internal server error"`.
- **Logging rules.** The access log records only method, path (no query string), status and time. Headers and bodies are never logged. Errors are logged by exception type only, because messages can contain user data.
- **Login failures look the same.** A wrong password and an unknown email both return `401 "Invalid email or password"`.
- **Audit log.** Register, login, failed login and logout are written to `audit_log` with the client IP. Passwords and tokens are never stored there. If the audit write fails, the request still succeeds. When an ingestion job finishes, one `ingest.job_finished` entry records the job kind, status, the `source` / `dry_run` settings and, per table, only the numbers `rows_read`, `rows_written` and `rejected_count`. Raw records, rejected-row samples and personal data are never stored there.
- **Pipeline audit entries.** `pipeline.job_started` and `pipeline.job_finished` record the job kind, status, settings (`force`, `dry_run`), the outcome (`loaded`, `already_loaded`, `reloaded`, `dry_run`), per-table counts and, for script runs, each step's name and exit code. Never row values, stdout or stderr.
- **Running the ML scripts.** Only the five allowlisted scripts run, with a fixed command line, no shell, no stdin, a timeout, and an environment that contains only `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR` and `PYTHONUNBUFFERED` (so no `SUPABASE_*` keys). The scripts' stdout is thrown away, because it contains user ids, IPs and amounts.
- **Auth lookup failures.** Errors while checking a token or loading a profile are logged by exception type only, never the token or the exception message. A Supabase outage gives `503`; only a token Supabase rejects gives `401`.
- **Response headers** on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- **CORS** allows only the origins in `CORS_ORIGINS`, with credentials off (tokens travel in the `Authorization` header, not cookies).
- **Rate limits** are per client IP. Behind a proxy every request may look like it comes from the proxy; trusted proxy headers are planned for Step 5.

## 10. Folder layout

```
backend/
├── .env.example        template for backend/.env (no real values)
├── .env                your secrets (git-ignored, create it yourself)
├── requirements.txt    API dependencies
├── pytest.ini          test settings
├── app/                the FastAPI application (all new backend code goes here)
│   ├── main.py         app factory: middleware, error handlers, routers
│   ├── config.py       settings from .env, with validation
│   ├── database.py     Supabase clients (admin, per-call anon, token verifier)
│   ├── security.py     get_current_user (401 / 403 / 503 mapping), require_role
│   ├── errors.py       the JSON error format
│   ├── audit.py        writes to audit_log
│   ├── jobs.py         in-memory job store and the one lock shared by ingestion and pipeline jobs
│   ├── rate_limit.py   per-IP rate limiter
│   ├── constants.py    positions and roles
│   ├── routers/        health.py, auth.py, admin.py, ingest.py, pipeline.py
│   └── services/       normalize.py (CSV parsing and mapping, no database),
│                       ingestion.py (chunked upserts, dry run, retries, summary),
│                       ml_adapter.py (runs the allowlisted ML scripts safely),
│                       ml_loader.py (parses and loads ml/output as one pipeline run),
│                       pipeline.py (glue for the pipeline routes)
├── sql/
│   ├── schema.sql          creates all tables, indexes and RLS
│   ├── verify_schema.sql   read-only checks
│   └── migrations/         002_ml_fields.sql (applied), 004_set_current_run.sql (run once)
├── tests/              pytest tests with a fake Supabase
│   └── fixtures/       data/ (small CSVs) and ml_output/ (synthetic ML output) for the tests
└── ml/                 Janvi's ML module (read-only for the API)
```

**Read-only for the API:** `backend/ml/` (Janvi) and `fsia_cyber/` (Aarushi, at the repo root) belong to other team members. The API must never modify them. Later steps will only read their output.

## 11. Troubleshooting

| Problem | Likely cause | Fix |
|---------|--------------|-----|
| Startup fails with `Invalid or missing configuration -> ...` | `backend/.env` is missing, or a value is empty or still a placeholder | Create it from `.env.example` and fill in the variable named in the message. |
| `SUPABASE_URL: must be the bare project URL ...` | The URL includes a path like `/rest/v1` or a query string | Use only `https://<project>.supabase.co`. |
| `CORS_ORIGINS: "*" is not allowed ...` | Wildcard origin | List the exact frontend origins, comma-separated. |
| `ModuleNotFoundError: No module named 'app'` | Command run from the wrong folder | Run `uvicorn` and `pytest` from `backend/`. |
| `GET /health/db` returns `503` | Wrong URL or key, Supabase project paused, or `schema.sql` not run | Check `.env`, check the project is active, run `sql/schema.sql`. |
| Browser shows a CORS error | The frontend origin is not in `CORS_ORIGINS` | Add its exact origin (scheme, host and port) and restart the server. |
| Login returns `401` right after registering | Email not confirmed | Set `AUTO_CONFIRM_EMAIL=true` and turn off **Confirm email** in Supabase (development). |
| Login or `/auth/me` returns `403 Account profile not found` | The auth user has no `profiles` row (for example, created in the Supabase dashboard instead of through `/auth/register`) | Register through the API, or add a matching `profiles` row in the SQL Editor. |
| `/admin/ping` returns `403` | The user's role is not `admin` | Promote the user (see **Roles**). |
| `429 Too many requests` | Rate limit reached (login 5/min, register 10/min) | Wait about a minute and try again. |
| `503 Service temporarily unavailable` on a logged-in route | Supabase could not be reached, returned a server error, or rate-limited the token / profile lookup | Check the Supabase project is active and reachable, then retry. The token is not necessarily bad. |
| `409 Another ingestion or pipeline job is already running` | An `/admin/ingest/...` or `/admin/pipeline/...` job has not finished | Poll its jobs route (`/admin/ingest/jobs/<JOB_ID>` or `/admin/pipeline/jobs/<JOB_ID>`) until it is `completed` or `failed`, then start the next one. |
| `409 Pipeline output is missing (run the pipeline first)` | Required files are not in `ML_OUTPUT_DIR` | Run `POST /admin/pipeline/run`, or run Janvi's scripts yourself (see `backend/ml/README.md`), then load again. |
| `409 pipeline_run_id differs ...` | The output files come from different pipeline runs | Rerun the pipeline so every file is regenerated together. Nothing was written. |
| A pipeline job fails with `set_current_run missing: run migration 004` | `sql/migrations/004_set_current_run.sql` was not run in Supabase | Run it once in the SQL Editor, then load again. The run is marked `failed` and the previous current run is untouched. |
| A pipeline job fails with `ML_PYTHON must be an absolute path ...` | `ML_PYTHON` is unset or relative | Set `ML_PYTHON` in `backend/.env` to an absolute path such as `<REPO>/.venv/bin/python3`. |
| A load returns `already_loaded` | A completed run with the same `pipeline_run_id` fingerprint already exists | Nothing to do. Use `force=true` only to re-upsert the same data into that run. |
| `GET /admin/ingest/jobs/<JOB_ID>` returns `404` | Unknown id, or the server restarted (job records are in memory) | Check `/admin/ingest/summary` for what is in the database; rerunning a load is safe. |
| An ingestion job ends with `status: "failed"` | A database write still failed after 4 attempts | Check Supabase is reachable, then run the load again; upserts make a rerun safe. |
| `/docs` returns `404` | `APP_ENV=production` | Use `APP_ENV=development` locally. |
