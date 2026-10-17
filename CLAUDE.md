# FSIA project rules
- NEVER modify anything in backend/ml/ (Janvi's work) or frontend/.
- Backend = FastAPI + Supabase. New backend code goes in backend/app/.
- Secrets only in backend/.env. Never print, log or commit them.
- Preserve dataset IDs (E..., A..., T...). Store pipeline_run_id on AI results.
- Run tests after every change. Never claim a test passed unless you ran it.
- Ask before deleting data, dropping tables, or deploying anything.
- Work one step at a time and stop for my confirmation.
- NEVER modify fsia_cyber/ (Aarushi's work). Read-only unless I explicitly approve otherwise.
