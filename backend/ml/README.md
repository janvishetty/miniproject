# Sentra AI/ML module (`backend/ml/`)

Detects attacks in the FinTech logs, groups them into incidents, explains why each was flagged, and writes
verified incident reports and Copilot answers with a local LLM. Everything runs on the laptop: no cloud APIs.

Owner: Janvi (AI/ML). This README is the handoff for the backend (FastAPI) and the frontend.

---

## 1. Setup (once)

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

The 5 dataset CSVs go in `data/` (`authentication_logs.csv`, `transactions.csv`, `users_devices.csv`,
`threat_indicators.csv`, `api_logs.csv`).

## 2. Run the pipeline

Run in this order from the repo root. Each step reads the previous step's output from `backend/ml/output/`.

| Step | Command | Time | Writes |
|---|---|---|---|
| 1. Clean data | `python3 backend/ml/preprocess.py` | ~5 s | `data/processed/*.csv`, `output/preprocessing_report.json` |
| 2. Features | `python3 backend/ml/features.py` | ~10 s | `output/auth_features.csv`, `output/txn_features.csv` |
| 3. Model + SHAP | `python3 backend/ml/model.py` | ~40 s | `output/scored_auth.csv`, `output/scored_txn.csv`, `output/iforest_*.joblib` |
| 4. Incidents | `python3 backend/ml/incidents.py` | ~5 s | `output/incidents.json`, `output/watchlist.json` |
| 5. Reports (LLM) | `python3 backend/ml/summarize.py` | ~5-10 s per report | `output/reports.json` |

`summarize.py` does all critical + high incidents by default (43 today) and caches: a rerun only generates
missing reports. Options: `--all`, `--id INC-2026-0081`, `--sev medium`, `--force`.

`backend/ml/output/` and `data/processed/` are git-ignored: rerun the scripts to regenerate them.

## 3. What the backend serves

### `GET /incidents` -> `output/incidents.json`

A list of incidents, sorted by risk (highest first). The first 11 fields match the frontend's mock
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
| `risk_score` | `99.5` | (confidence + impact) / 2; drives `sev` |
| `start`, `end` | `2026-09-10T01:15:45` | ISO timestamps |
| `users`, `ips`, `event_ids` | lists | Everything involved |
| `event_count`, `amount_total` | `11`, `89100.0` | Amount in rupees |
| `ip_threat_level` | `High` | Highest threat-feed level among its IPs (`None` if on no feed) |
| `ip_details` | `[{"ip", "threat", "usual_for_user"}]` | Per IP; `usual_for_user: true` = the customer's own IP (never block it) |
| `reasons` | `[{"feature", "impact", "text"}]` | SHAP: why it was flagged, e.g. `"IP on threat list (High)"` |
| `sequence` | `{failed_logins, failed_window, successful_logins, transfers}` | The attack in order, with IDs, times, amounts, merchants |
| `timeline` | `[{"time", "actor", "msg", "color"}]` | Newest first, same shape as the frontend's `TIMELINE` mock |

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
inc = next(i for i in json.load(open("backend/ml/output/incidents.json")) if i["id"] == "INC-2026-0124")
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

Suggested frontend chips (replace the mock ones in `AICopilotPage.tsx`):
"Summarize the critical incidents", "What caused INC-2026-0081?", "Generate a remediation plan for the account
takeovers", "How many incidents are there by type?", "What happened to user U0063?", "Explain the credential
stuffing from Moscow".

## 4. Things to know

- **Incident IDs are not stable across reruns.** Rerunning `incidents.py` after the data or code changes can
  renumber them. Don't store IDs in the database without the run they came from.
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

Current results: cash-out transfers caught 53/53; planted attacks 84% (easy 99%, stealthy 70%);
precision 68% before noise filters, 86% after; 43/43 reports verified. Labelled review sheets are in `docs/`.

## 6. Pending: rules from Aarushi (hybrid detection)

When the rule engine is ready, it should write **`data/rule_alerts.csv`**:

```
event_id,rule_id,rule_name,severity,timestamp
E020221,R-101,Credential stuffing (>10 failures per IP per hour),high,2026-09-08 22:41:05
T002429,R-104,Transfer > 10x user average,critical,2026-09-10 01:33:15
```

`event_id` must be the dataset's own `event_id` (logins) or `transaction_id` (transfers). `incidents.py` will
then merge rule hits into incidents and their timelines.

## Files

| File | Purpose |
|---|---|
| `preprocess.py` | Validate and clean the raw CSVs |
| `features.py` | Per-event features |
| `model.py` | Isolation Forest + SHAP |
| `incidents.py` | Group into incidents, classify, noise filter |
| `summarize.py` | Verified LLM incident reports |
| `copilot.py` | Verified LLM chat answers |
| `evaluate.py`, `inject_test.py`, `review_sheet.py` | Evaluation |
| `requirements.txt` | Python packages |
