# Vantix: FinTech Security Investigation Assistant (FSIA)

## What it is

Vantix helps analysts investigate security incidents in FinTech logs. A rule engine and an Isolation Forest model
(explained with SHAP) both flag suspicious events, and they are merged into one incident list. A local LLM (Ollama)
writes fact-checked incident reports and answers questions in the AI Copilot. Analysts stay in the loop: they review
incidents and change their status.

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

## Quick start (3 terminals)

Prerequisites:

- Python 3.11+ (separate virtual environments for `backend/` and `backend/ml/`)
- Node 22
- Ollama with the model pulled: `ollama pull llama3.2:3b`
- A Supabase project, with the schema from `backend/sql/` applied
- `backend/.env` created from `backend/.env.example` (it holds secrets; never commit it)

Setup of the database, loading the data and running the pipeline are admin steps described in
[backend/README.md](backend/README.md).

```bash
# Terminal 1: the local LLM
ollama serve

# Terminal 2: the API on port 8000 (activate the backend venv first)
cd backend
CORS_ORIGINS=http://localhost:8443,http://127.0.0.1:8443 uvicorn app.main:app --port 8000

# Terminal 3: the frontend on port 8443
cd frontend
npx pnpm@10.34.3 install
npx pnpm@10.34.3 dev
```

`CORS_ORIGINS` can also be set in `backend/.env`. Without Ollama everything still works except Copilot questions and
report generation.

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

## Running the ML pipeline by hand

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
