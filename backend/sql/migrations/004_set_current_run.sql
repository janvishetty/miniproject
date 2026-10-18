-- 004: set_current_run(run_id)
-- Run once in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query -> Run).
-- Safe to re-run (create or replace). Requires migration 002 (source_fingerprint) to be applied first.
--
-- Makes one completed pipeline run the "current" run, in a single atomic call:
-- the old current run is switched off and the new one on inside the same function,
-- so the unique index one_current_run is never violated. The API calls this through
-- rpc("set_current_run", {"run_id": ...}); it never flips is_current with two writes.

create or replace function public.set_current_run(run_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not exists (select 1 from public.pipeline_runs where id = run_id and status = 'completed') then
    raise exception 'pipeline run % is not completed (or does not exist)', run_id;
  end if;

  update public.pipeline_runs set is_current = false where is_current;
  update public.pipeline_runs set is_current = true where id = run_id;
end;
$$;

revoke all on function public.set_current_run(uuid) from public, anon, authenticated;
grant execute on function public.set_current_run(uuid) to service_role;
