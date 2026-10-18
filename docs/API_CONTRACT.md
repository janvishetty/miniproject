# API contract (Step 4: read APIs)

Base URL `http://127.0.0.1:8000`. Every route below needs `Authorization: Bearer <access_token>`
(from `POST /auth/login`). Errors always look like

```json
{"error": {"code": "not_found", "message": "Incident not found", "details": [{"field": "x", "message": "..."}]}}
```

(`details` only on 422.) Codes: `unauthorized` 401, `forbidden` 403, `not_found` 404, `conflict` 409,
`validation_error` 422, `rate_limited` 429, `unavailable` 503, `gateway_timeout` 504, `server_error` other 5xx.

**Current run.** Every route reads the pipeline run with `is_current = true`. With none loaded the
answer is `409 {"error": {"code": "conflict", "message": "no pipeline run loaded yet"}}`.

**Incident id** in paths must match `^INC-\d{4}-\d{4}$`, else `422`. Unknown id in the current run: `404`.

## Frontend setup

| Setting | Where | Value |
|---|---|---|
| `VITE_API_URL` | frontend (read by Vite) | default `http://127.0.0.1:8000` |
| `CORS_ORIGINS` | `backend/.env` | `http://localhost:8443,http://127.0.0.1:8443` (Vite runs on 8443) |

Restart the backend after changing `CORS_ORIGINS`. Do not create `frontend/.env.example`.

## Endpoints

| Method | Path | Role | Frontend page |
|---|---|---|---|
| GET | `/dashboard` | any authenticated | DashboardPage |
| GET | `/incidents` | any | IncidentsPage |
| GET | `/incidents/{id}` | any | IncidentsPage (detail panel) |
| GET | `/incidents/{id}/events` | any | IncidentsPage (evidence) |
| PATCH | `/incidents/{id}` | analyst (limited) / manager / admin | IncidentsPage (status, assign, Resolve) |
| GET | `/reports` | any | LLIReportsPage (incident reports) |
| GET | `/reports/{id}` | any | LLIReportsPage |
| POST | `/incidents/{id}/report` | any | IncidentsPage / LLIReportsPage ("Generate report") |
| GET | `/reports/jobs/{job_id}` | job owner, manager, admin | polling for the above |
| POST | `/copilot` | any | AICopilotPage |
| GET | `/copilot/welcome` | any | AICopilotPage (opening message) |

### GET /dashboard

Live from `incidents` (status changes show immediately), the rest from the run's dashboard snapshot.

```json
{
  "run": {"id": "5b0e3a52-...", "fingerprint": "abc123def456", "loaded_at": "2026-10-18T09:05:00+00:00"},
  "active_incidents": 4, "critical_open": 1, "platform_risk_score": 80,
  "by_severity": {"critical": 1, "high": 1, "medium": 1, "low": 1},
  "by_status": {"OPEN": 4, "INVESTIGATING": 0, "CONTAINED": 0, "RESOLVED": 0},
  "by_type": {"Account Takeover": 2, "Brute Force": 2},
  "recent": [{"id": "INC-2026-0081", "sev": "critical", "title": "...", "time": "09:15", "status": "OPEN", "started_at": "..."}],
  "events_analysed": 2000, "events_analysed_sub": "...", "anomalous_events": 12,
  "event_funnel": {}, "amount_at_risk": 1234.5,
  "risk_map_title": "API Endpoint Risk Map", "risk_map": [], "live_events": [], "model": {},
  "avg_response_time": null
}
```

* `active_incidents` = status is not RESOLVED. `critical_open` = critical and OPEN or INVESTIGATING.
* `platform_risk_score` = severity-weighted mean risk (critical 4, high 3, medium 2, low 1) of non-resolved incidents.
* `by_severity` and `by_type` count non-resolved incidents; `by_status` counts all. `recent` = 10 newest by `started_at`.
* Snapshot fields are passed through as stored (null if the snapshot is missing). `avg_response_time` is always `null`
  (no source). There are no trend / "up N pts" fields.

### GET /incidents

Query: `severity` (critical|high|medium|low), `status` (OPEN|INVESTIGATING|CONTAINED|RESOLVED), `vector`
(Account Takeover|Credential Stuffing|Brute Force|Suspicious Login|Transaction Anomaly), `search` (max 100 chars),
`sort` (`risk_score` default, `started_at`, `confidence`), `order` (`desc` default, `asc`), `page` (>=1, default 1),
`page_size` (1..100, default 20). Anything else: 422. Rows with a null sort value come last.

```json
{"items": [{"id": "INC-2026-0081", "sev": "critical", "status": "OPEN", "title": "...", "asset": "...",
            "ip": "10.0.0.1", "analyst": "Unassigned", "vector": "Account Takeover", "created": "09:15",
            "confidence": 98, "impact": 90, "started_at": "2026-09-01T09:15:00+00:00", "risk_score": 95.0}],
 "total": 61, "page": 1, "page_size": 20}
```

`created` is the incident's original time text, else `started_at` as UTC `HH:MM`.
`search` is a plain substring (case-insensitive) over title, asset, IP, id, analyst and vector. Every character is
literal (`% _ * , ( ) " \` are escaped). More than 300 matches: `422 "search too broad, add a filter"` (nothing is
cut off; add `severity`/`status`/`vector` to narrow it).

### GET /incidents/{id}

The list item plus `ended_at, event_count, amount_total, ip_threat_level, users, ips, ip_details, reasons, sequence,
timeline, detected_by, ml_severity, rule_severity, rule_hits, rule_mitre, threat_actor, threat_intel, ai_summary`,
`event_ids` (list) and `report` (`{summary, source, grounded, created_at}` or `null`).

### GET /incidents/{id}/events

Query `page` (default 1), `page_size` (1..100, default 50). Events of the incident ordered by time:
`{"items": [{"event_id","event_kind","source_type","ts","user_id","ip_address","device_id","location","status",
"mfa_status","endpoint","http_method","status_code","amount","merchant"}], "total", "page", "page_size"}`.

### PATCH /incidents/{id}

Body: `status` and/or `analyst_id` (a profile uuid or `null`). Any other field, an empty body, `status: null` or an
unknown status: `422`. Returns the updated list item. Writes an `incident.updated` audit row (actor, before/after
status and analyst).

| Role | status | analyst_id |
|---|---|---|
| analyst | OPEN, INVESTIGATING, CONTAINED (RESOLVED: 403) | only their own id (other id or `null`: 403) |
| manager, admin | any, including RESOLVED | any existing profile; `null` sets "Unassigned" |

The server writes the profile's name into `analyst`; an unknown `analyst_id` is `422`.

### Reports

`GET /reports?page=&page_size=` returns `{"items": [...], "total", "page", "page_size"}` (empty: `200` with
`"items": []`, `"total": 0`), newest first. Item: `{id, title, sev, summary, five_ws, mitre, containment_actions,
investigation_steps, source, grounded, unverified, created_at}`. `GET /reports/{id}` returns one item;
no report: `404 "No report for this incident yet"`.

`POST /incidents/{id}/report` -> `202`
`{"job_id": "...", "incident_id": "INC-2026-0081", "status": "running", "error": null, "result": null, ...}`.
One report job at a time: a second request gets `429 "report generation busy"`. Poll
`GET /reports/jobs/{job_id}` (always `200`; only the user who started it, or a manager/admin; others get `404`):

```json
{"job_id": "...", "incident_id": "INC-2026-0081", "status": "completed",
 "error": null, "result": {"incident_id": "INC-2026-0081", "source": "llm", "grounded": true},
 "started_at": "...", "finished_at": "..."}
```

`status` is `running | completed | failed`. On failure `error` is `{code, message}`:

| code | message |
|---|---|
| `ai_unavailable` | AI service unavailable - start Ollama |
| `timeout` | AI service timed out (limit 600 s) |
| `unverified` | report could not be verified (`grounded` is false; nothing stored) |
| `stale_run` | the pipeline run changed; reload and try again |
| `error` | report generation failed |

A report is stored only when `grounding.grounded` is true, whatever its source (`llm`, `llm_corrected`, or the
verified `template` fallback, which keeps `source: "template"`). Regenerating replaces the stored report.

### Copilot

`POST /copilot` body `{"question": "..."}` (1..500 chars after trimming; extra fields: 422) ->
`{"answer": "markdown", "incidents": ["INC-..."], "source": "llm|llm_corrected|facts", "grounding": {...}, "seconds": 1.2}`.
The question is not echoed. The Copilot sees ALL current-run incidents with their live status and analyst.

* 10 questions per minute per user: `429` with `Retry-After`. One call at a time: `429 "copilot busy"`.
* Ollama down: `503 "AI service unavailable - start Ollama"`. Over 120 s: `504`. Unusable bridge output: `502`.

`GET /copilot/welcome` -> same shape; built by code from the non-resolved incidents, needs no Ollama.

## Step 4 decisions

**Roles**

| Action | analyst | manager | admin |
|---|---|---|---|
| Read dashboard, incidents, events, reports | yes | yes | yes |
| Ask Copilot, generate a report | yes | yes | yes |
| Set status OPEN / INVESTIGATING / CONTAINED | yes | yes | yes |
| Set status RESOLVED | no | yes | yes |
| Assign an incident | only to self | anyone | anyone |
| Unassign | no | yes | yes |
| Read another user's report job | no | yes | yes |
| `/admin/*` | no | no | yes |

* **Copilot audit** records the user id, the question LENGTH, the answer source and the incident ids mentioned. The
  question text is never stored, logged, or put on a command line (it goes to the bridge on stdin only).
* **Force reload keeps work.** `load(force=true)` into an existing run keeps the current status and analyst of
  incidents that already exist; everything else is refreshed from the files. New runs start from the file as before.
* **CORS** allows `http://localhost:8443` and `http://127.0.0.1:8443` (Vite port 8443), set in `CORS_ORIGINS`.
* **Request logging.** The `httpx` / `httpcore` loggers are WARNING so Supabase request URLs (user ids) are not logged.

**Frontend items decided for the later frontend branch** (not part of Step 4; `frontend/` is untouched):

1. LoginPage gets a Sign in / Create account switch.
2. Escalate stays a toast, with the PagerDuty text removed.
3. A Resolve button, shown to manager/admin only.
4. Incident reports are shown, and the compliance tabs carry a "Sample data" tag.
5. The access token is kept in memory only (not localStorage).
6. Incident list paging: Previous / Next, 20 per page.
7. Copilot shows an offline message with a Retry button when it gets 503/504.
8. Avg Response Time shows "—" (the API returns `null`).
