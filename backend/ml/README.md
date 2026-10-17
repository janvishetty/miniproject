# AI/ML module (`backend/ml/`)

Detects attacks in the FinTech logs, groups them into incidents, explains why each was flagged, and writes
verified incident reports and Copilot answers with a local LLM. Everything runs on the laptop: no cloud APIs.

Owner: Janvi (AI/ML). This README is the handoff for the backend (FastAPI) and the frontend.

---

## 1. Setup (once)

Needs **Python 3.11 or newer** (check with `python3 --version`); pandas 3 does not install on 3.10.

```bash
cd miniproject
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/ml/requirements.txt
```

The LLM parts need **Ollama** running with the model pulled:

```bash
ollama pull llama3.2:3b      # ~2 GB, once
ollama serve                 # or just open the Ollama app
```

The 5 dataset CSVs are in `data/` (`authentication_logs.csv`, `transactions.csv`, `users_devices.csv`,
`threat_indicators.csv`, `api_logs.csv`), with the answer key `ground_truth_*.csv` (read only by `evaluate.py`).

## 2. Run the pipeline

Run in this order from the repo root. Each step reads the previous step's output from `backend/ml/output/`.

| Step | Command | Time | Writes |
|---|---|---|---|
| 1. Clean data | `python3 backend/ml/preprocess.py` | ~5 s | `data/processed/*.csv`, `output/preprocessing_report.json` |
| 2. Features | `python3 backend/ml/features.py` | ~10 s | `output/auth_features.csv`, `output/txn_features.csv` |
| 3. Model + SHAP | `python3 backend/ml/model.py` | ~40 s | `output/scored_auth.csv`, `output/scored_txn.csv`, `output/iforest_*.joblib` |
| 4. Incidents (hybrid) | `python3 backend/ml/incidents.py` | ~15 s | `output/incidents.json`, `output/watchlist.json` |
| 5. Reports (LLM) | `python3 backend/ml/summarize.py` | ~5-10 s per report | `output/reports.json` |
| 6. Dashboard data | `python3 backend/ml/frontend_data.py` | ~2 s | `output/dashboard.json` |

Step 4 also runs Aarushi's rule engine (`fsia_cyber/rules.py`) and merges its hits in; `--no-rules` gives ML only.

`summarize.py` does all critical + high incidents by default (75 today) and caches: a rerun only generates
missing reports. Options: `--all`, `--id INC-2026-0081`, `--sev medium`, `--force`.

`backend/ml/output/` and `data/processed/` are git-ignored: rerun the scripts to regenerate them.

## 3. What the backend serves

### `GET /incidents` -> `output/incidents.json`

A list of incidents (203 today), sorted by risk (highest first). The first 11 fields match the frontend's mock
`ALL` array in `IncidentsPage.tsx`, so the page can use them as-is.

| Field | Example | Meaning |
|---|---|---|
| `id` | `INC-2026-0081` | Incident ID |
| `sev` | `critical` | `critical` / `high` / `medium` / `low` |
| `status` | `OPEN` | Always `OPEN` from the AI side; analysts change it |
| `title` | `Account Takeover: ₹89,100 Transferred After Suspicious Access` | |
| `asset` | `payments-api /api/v1/transfer` | |
| `ip` | `45.12.100.55` | Main source IP |
| `analyst` | `Unassigned` | |
| `vector` | `Account Takeover` | `Account Takeover`, `Credential Stuffing`, `Brute Force`, `Transaction Anomaly`, `Suspicious Login` |
| `created` | `01:15` | Start time (HH:MM) |
| `confidence` | `100` | Max anomaly score of its events, 0-100 |
| `impact` | `99` | 0-100, from attack type, money moved, threat level |
| `risk_score` | `99.5` | (confidence + impact) / 2; drives the ML severity |
| `start`, `end` | `2026-09-10T01:15:45` | ISO timestamps |
| `users`, `ips`, `event_ids` | lists | Everything involved |
| `event_count`, `amount_total` | `11`, `89100.0` | Amount in rupees |
| `ip_threat_level` | `High` | Highest threat-feed level among its IPs (`None` if on no feed) |
| `ip_details` | `[{"ip", "threat", "usual_for_user"}]` | Per IP; `usual_for_user: true` = the customer's own IP (never block it) |
| `reasons` | `[{"feature", "impact", "text"}]` | SHAP: why it was flagged, e.g. `"IP on threat list (High)"` |
| `sequence` | `{failed_logins, failed_window, successful_logins, transfers}` | The attack in order, with IDs, times, amounts, merchants |
| `timeline` | `[{"time", "actor", "msg", "color"}]` | Newest first, same shape as the frontend's `TIMELINE` mock; includes `Rule Engine` rows |
| `detected_by` | `ml+rules` | `ml`, `rules` or `ml+rules` (hybrid detection) |
| `rule_hits` | `[{"rule", "name", "events", "first"}]` | Rules that fired on this incident's events, e.g. `R_BRUTE_FORCE` |
| `ml_severity`, `rule_severity` | `high`, `critical` | `sev` is the higher of the two (`rule_severity` is `null` if no rule fired) |
| `ml_event_ids` | list | The events the model itself flagged (the rest came from rules) |
| `threat_actor` | `Linked to credential-stuffing campaign (Partner bank share, High)` | For the "Threat Actor" card; `Unknown - IP not on any threat feed` if none |
| `threat_intel` | `{"ip", "level", "description", "source", "last_seen"}` or `null` | The threat-feed entry behind `threat_actor` |
| `ai_summary` | `8 failed logins from 45.12.100.55 against U0214 …` | "AI Analysis" text for EVERY incident (code-built, verified). If `reports.json` has this ID, show its LLM `summary` instead |

`GET /incidents/{id}` = one item of that list.

`output/watchlist.json` holds low-value alerts filtered out of the incident list (failed small payments,
logins from the customer's own IP and device). Optional to show.

### `GET /reports/{id}` -> `output/reports.json`

A list of verified incident reports (critical + high). Key fields:

| Field | Meaning |
|---|---|
| `id`, `title`, `sev`, `vector`, `confidence`, `impact` | Copied from the incident |
| `summary` | 2-3 sentence narrative of the attack |
| `five_ws` | `{who, what, when, where, why_flagged}`, written by code from the data |
| `mitre` | MITRE ATT&CK techniques, e.g. `["T1078 Valid Accounts", "T1110 Brute Force"]` |
| `containment_actions` | Block / lock / freeze / hold / MFA steps, written by code per attack type |
| `investigation_steps` | 2 follow-up checks |
| `source` | `llm`, `llm_corrected` (passed after a retry) or `template` (LLM failed 3 times; code-built text) |
| `grounding` | `{grounded, unverified}`: every published report has `grounded: true` |

On-demand report for an incident that has none yet:

```python
from backend.ml.summarize import summarize
import json
inc = next(i for i in json.load(open("backend/ml/output/incidents.json")) if i["id"] == "INC-2026-0079")
report = summarize(inc)          # ~5-30 s, needs Ollama running
```

### `POST /copilot` -> `copilot.answer(question)`

```python
from backend.ml.copilot import answer

@app.post("/copilot")
def copilot(body: dict):
    return answer(body["question"])      # ~3-30 s, needs Ollama running
```

Returns:

| Field | Meaning |
|---|---|
| `answer` | Markdown for the chat (the frontend already renders `**bold**`), ending with a "Containment (from the data)" section |
| `incidents` | Incident IDs the answer is about (can link to `/incidents/{id}`) |
| `source` | `llm`, `llm_corrected` or `facts` (LLM failed checks 3 times; answer built from the data) |
| `grounding` | `{grounded, unverified}` |
| `seconds` | How long it took |

It understands incident IDs, user IDs (`U0214`), IPs, transaction IDs (`T002428`), attack types, places
("Moscow"), severities and "how many / summarize" questions. Unknown IDs get "No incident in the current data
involves …". Try it: `python3 backend/ml/copilot.py --demo`.

`welcome()` returns the opening message (same shape as `answer`, built from the data, instant, no Ollama) to
replace the mock `ANSWERS.default`: `GET /copilot/welcome`.

Suggested frontend chips (replace the mock ones in `AICopilotPage.tsx`):
"Summarize the critical incidents", "What caused INC-2026-0081?", "Generate a remediation plan for the account
takeovers", "How many incidents are there by type?", "What happened to user U0063?", "Explain the credential
stuffing from Moscow".

## 3b. Frontend page by page

| Page / element (frontend/src) | Replace the mock with | Notes |
|---|---|---|
| Dashboard stat cards | `dashboard.json` -> `stats` (`active_incidents`, `critical`, `platform_risk_score`, `events_analysed` + `*_sub` texts) | "Avg Response Time" is analyst workflow data, not ML: keep or drop |
| Dashboard risk map (`RISK_NODES`) | `dashboard.json` -> `risk_map` (`id, tag, score, alerts, risk`) | One node per API endpoint, from `api_logs.csv` |
| Dashboard live events (`STREAM_POOL`) | `dashboard.json` -> `live_events` (`ts, node, msg, type`) | Newest first, `type` is `alert`/`warn` |
| Dashboard recent incidents (`RECENT`) | `dashboard.json` -> `recent` (`id, sev, title, time, status`) | |
| Incidents list + detail (`ALL`) | `GET /incidents` | Same field names |
| Incidents "Threat Actor" (hard-coded) | `threat_actor` | |
| Incidents "AI Analysis" paragraph | `reports.json` `summary` if present, else `ai_summary` | Model label: "llama3.2:3b + Isolation Forest/SHAP" instead of "finbert-vantix-v2.1" |
| Incidents timeline (`TIMELINE`) | `timeline` | Includes `Rule Engine` rows |
| Incidents "Generate Report" button | `GET /reports/{id}` (or `summarize(inc)` on demand for medium/low) | |
| Copilot chat | `POST /copilot` -> `answer` (markdown in the page's `renderText` format) | |
| Copilot opening message (`ANSWERS.default`) | `GET /copilot/welcome` -> `welcome()` | |
| Copilot side panel "Model" | `llama3.2:3b (Ollama)` | "Method: Rule + ML hybrid" is now true |
| Reports page (PCI-DSS / SOX / GDPR cards) | not ML output | Our reports are incident reports (`reports.json`), not compliance reports: list them in "All Reports" (one card per report: `id`, `title`, `sev`, `source`) or keep the compliance page as a static mock |

`status` is always `OPEN` from the AI side; the buttons (Contain / Escalate / Resolve) and status filters are
backend state.

## 3c. Loading the outputs into the database (`backend/sql/schema.sql`)

| Table | Fill from | Watch out |
|---|---|---|
| `pipeline_runs` | `output/pipeline_run.json` | Our `pipeline_run_id` is a 12-char fingerprint, not a uuid: keep your uuid and store ours alongside (e.g. in `notes`) to spot reruns that changed nothing |
| `ml_results` | `output/scored_auth.csv` + `scored_txn.csv` (`event_id` / `transaction_id`, `anomaly_score` 0-100, `top_reasons` JSON) | `is_anomalous` = **`is_flagged`**, NOT `is_anomaly`. `is_anomaly` is the raw Isolation Forest label (2,689 logins); incidents use `is_flagged` (score >= 70 logins / >= 60 transfers: 952 + 119) |
| `rule_alerts` | `output/rule_alerts.csv` (`event_id, rule_id, rule_name, severity, timestamp`) | Written by `incidents.py` from the fsia_cyber rules; one row per (event, rule) |
| `incidents` | `output/incidents.json` | Extra fields not in the table yet: `detected_by`, `rule_hits`, `ml_severity`, `rule_severity`, `ml_event_ids`, `threat_actor`, `threat_intel`, `ai_summary`, `created` (HH:MM the frontend shows) |
| `incident_events` | `event_ids` of each incident | |
| `correlation_results` | not needed: the rule engine's correlation is already merged into each incident (`rule_hits`), MITRE is in `reports.json` | fsia_cyber's own `incidents.json` (INC-0001…) is a separate list, not 1:1 with ours |
| `reports` | `output/reports.json` | Also carries `detected_by`, `rule_hits`, `pipeline_run_id` |

## 4. Things to know

- **Incident IDs are not stable across reruns.** Rerunning `incidents.py` after the data or code changes can
  renumber them. Every incident, report and `dashboard.json` carries `pipeline_run_id` (also in
  `output/pipeline_run.json`): a fingerprint of the exact incident set. Same id = same incidents; store it with
  anything you save, and treat a new id as a new run.
- **Ollama must be running** for `/copilot` and on-demand reports. If it isn't, the scripts raise
  "Can't reach Ollama at http://localhost:11434…"; the API should return a 503 with that message.
- **LLM calls are slow** (3-30 s). Call them from a background task or show a loading state; don't block the page.
- **Never show unverified text.** Everything in `reports.json` and every `answer()` result has already passed
  the grounding check; nothing else needs filtering.
- **The customer's own IP**: actions say "Do NOT block …" for IPs where `usual_for_user` is true.

## 5. Evaluation

```bash
python3 backend/ml/inject_test.py     # ~4 min: 400 planted attacks, 5 seeds
python3 backend/ml/evaluate.py        # prints all results, writes output/evaluation.json
```

Results:

| Check | Result |
|---|---|
| **Ground truth** (answer key, 195 planted attacks) | ML only 194/195 (99.5%), 9 false-positive incidents of 202, all low severity. Hybrid 195/195, 9 of 203 |
| Proxy test (no labels) | cash-out transfers caught 53/53 |
| Own attack injection | 84% overall (easy 100%, stealthy 68%) |
| Analyst review | precision 68% before noise filters, 86% after |
| Reports | every published report passes the grounding check |

Labelled review sheets are in `docs/`. The answer key arrived after sections A-C were built, so those are the
"no ground truth" checks; section D confirms them with real labels.

## 6. Hybrid detection (rules from Aarushi)

`incidents.py` loads `fsia_cyber/rules.py` + `correlate.py` by file path and runs them on `data/`:

- every rule alert's events are matched to the ML incidents -> `rule_hits`, `detected_by`, Rule Engine timeline rows
- events a strong rule flagged but the model scored below threshold are added (rules-only catches: 1 today)
- `sev` = higher of ML and rule severity; rule-confirmed incidents are never moved to the watch-list
- `R_IMPOSSIBLE_TRAVEL_CANDIDATE` and `R_NEW_BENEFICIARY` are context only: they annotate but never create incidents
- if `fsia_cyber/` is missing, the script prints a note and runs ML-only

## Files

| File | Purpose |
|---|---|
| `preprocess.py` | Validate and clean the raw CSVs |
| `features.py` | Per-event features |
| `model.py` | Isolation Forest + SHAP |
| `incidents.py` | Group into incidents, classify, noise filter |
| `summarize.py` | Verified LLM incident reports |
| `copilot.py` | Verified LLM chat answers |
| `frontend_data.py` | `dashboard.json` for the Dashboard page |
| `evaluate.py`, `inject_test.py`, `review_sheet.py` | Evaluation |
| `requirements.txt` | Python packages |
