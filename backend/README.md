# FSIA / CirionSOC backend (FastAPI)

The API server for the FSIA / CirionSOC project. It is built with **FastAPI** and uses **Supabase** (PostgreSQL + Supabase Auth). The frontend talks only to this API, never to the database directly.

This document covers only what exists in the code today.

## Status

| Step | Scope | Status |
|------|-------|--------|
| 1 | Foundation and auth: config, Supabase clients, error format, logging, security headers, rate limiting, register / login / me / logout, roles, audit log, database schema | **Done** |
| 2 | CSV ingestion (`data/` → `raw_events`, `events`, reference tables) | Planned |
| 3 | ML pipeline integration (`backend/ml/`, `fsia_cyber/` results → `pipeline_runs`, AI result tables) | Planned |
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
| `DATA_DIR` | No (default `../data`) | CSV folder. For later steps; not used yet. |
| `ML_OUTPUT_DIR` | No (default `backend/ml/output`) | Folder with the ML module's output. For later steps; not used yet. |
| `ML_PYTHON` | No (default `python3`) | Python command for running the ML module. For later steps; not used yet. |

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

The tests never touch your real Supabase project. [tests/conftest.py](tests/conftest.py) sets fake environment variables before the app is imported and replaces the Supabase clients with an in-memory fake. Rate limiting is off during tests, except in the test that checks it.

| File | What it covers |
|------|----------------|
| [tests/test_config.py](tests/test_config.py) | Settings validation: missing / placeholder values, URL format, wildcard CORS, secrets kept out of errors and `repr` |
| [tests/test_auth.py](tests/test_auth.py) | Health checks, security headers, error format, register, login, rate limit, `/auth/me`, roles, logout, audit log contents, docs turned off in production |

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
| GET | `/docs`, `/redoc`, `/openapi.json` | Public, development only | – | API docs. Return `404` when `APP_ENV=production`. |

Logged-in routes need the header `Authorization: Bearer <access_token>`.

Input rules for `/auth/register`:

- `username`: 3–30 characters, letters, digits, `_`, `.` and `-`. Stored in lower case.
- `email`: stored in lower case. Login is not case-sensitive for email.
- `password`: 8–128 characters.
- `position`: one of `Security Analyst`, `Senior Analyst`, `SOC Manager`, `Threat Intelligence Lead`, `Compliance Officer`, `Platform Engineer`, `CISO / CTO` (must match the frontend's login form).
- Unknown fields, including `role`, are ignored.

Status codes: `401` = missing, invalid or expired token. `403` = valid user without permission, or no profile row. `409` = username or email already taken. `422` = invalid input. `429` = rate limit reached. `503` = Supabase unavailable.

## 6. Roles

Every account has one role in `profiles.role`:

| Role | Who | Notes |
|------|-----|-------|
| `analyst` | Everyone who registers | Default. The public API can never set any other role. |
| `manager` | Promoted by an admin | Exists in the schema; no route needs it yet. |
| `admin` | Promoted by an admin | Can call `/admin/ping`. |

**Promote a user to admin.** Run this in **Supabase → SQL Editor**, with the user's own email:

```sql
update public.profiles set role = 'admin' where email = 'you@example.com';

-- check
select id, username, email, role from public.profiles;
```

Use `'manager'` the same way. The role is read from the database on every request, so the change applies immediately; the user does not need to log in again.

## 7. Security notes

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
- **Audit log.** Register, login, failed login and logout are written to `audit_log` with the client IP. Passwords and tokens are never stored there. If the audit write fails, the request still succeeds.
- **Response headers** on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- **CORS** allows only the origins in `CORS_ORIGINS`, with credentials off (tokens travel in the `Authorization` header, not cookies).
- **Rate limits** are per client IP. Behind a proxy every request may look like it comes from the proxy; trusted proxy headers are planned for Step 5.

## 8. Folder layout

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
│   ├── security.py     get_current_user, require_role
│   ├── errors.py       the JSON error format
│   ├── audit.py        writes to audit_log
│   ├── rate_limit.py   per-IP rate limiter
│   ├── constants.py    positions and roles
│   ├── routers/        health.py, auth.py, admin.py
│   └── services/       empty, for later steps
├── sql/
│   ├── schema.sql          creates all tables, indexes and RLS
│   └── verify_schema.sql   read-only checks
├── tests/              pytest tests with a fake Supabase
└── ml/                 Janvi's ML module (read-only for the API)
```

**Read-only for the API:** `backend/ml/` (Janvi) and `fsia_cyber/` (Aarushi, at the repo root) belong to other team members. The API must never modify them. Later steps will only read their output.

## 9. Troubleshooting

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
| `/docs` returns `404` | `APP_ENV=production` | Use `APP_ENV=development` locally. |
