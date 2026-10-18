# FSIA project rules (read before every task)
## Ownership
- NEVER modify backend/ml/ (Janvi), fsia_cyber/ (Aarushi), frontend/ (unless I name the exact files), data/.
- Backend code: backend/app/, backend/sql/, backend/tests/, backend/README.md, docs/.
## Secrets and git
- Secrets only in backend/.env. Never open, print, log or commit it. Never echo env values.
- NEVER commit backend/ml/output/ or data/processed/. Never use git add -f. Never force-push, never git pull.
- Generated ML output is read-only input: never edit or delete files in backend/ml/output/.
## Data
- Preserve dataset ids (E..., A..., T...). Never read ground_truth_*.csv.
- Our own uuid per pipeline run; Janvi's 12-char pipeline_run_id goes in pipeline_runs.source_fingerprint.
- is_flagged (never is_anomaly) means anomalous. Severity stored lowercase.
## Working method
- One step at a time; stop at every checkpoint and wait for my word ("approved", "go", "apply").
- Show the diff of every EXISTING file before changing it. New files: plan first.
- No real database writes, no DROP/TRUNCATE/DELETE, no deploys, no installs without asking.
- Run tests after every change. Never claim anything passed unless you ran it and show the output.
- Logs and errors: exception TYPE only, no row values, no tokens.
- If something in the files differs from what I told you, report it; do not "fix" the data to match.