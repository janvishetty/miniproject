-- 002: Already applied in Supabase on 18 Oct 2026. Do NOT run again.
alter table pipeline_runs add column if not exists source_fingerprint text;
create unique index if not exists uq_runs_completed_fingerprint
  on pipeline_runs (source_fingerprint) where source_fingerprint is not null and status = 'completed';

alter table incidents
  add column if not exists detected_by text,
  add column if not exists rule_hits jsonb not null default '[]',
  add column if not exists ml_severity text,
  add column if not exists rule_severity text,
  add column if not exists ml_event_ids jsonb not null default '[]',
  add column if not exists rule_mitre jsonb not null default '[]',
  add column if not exists threat_actor text,
  add column if not exists threat_intel jsonb,
  add column if not exists ai_summary text,
  add column if not exists raw jsonb;

create table if not exists dashboard_snapshots (
  id uuid primary key default gen_random_uuid(),
  pipeline_run_id uuid not null unique references pipeline_runs(id) on delete cascade,
  payload jsonb not null,
  created_at timestamptz not null default now());
alter table dashboard_snapshots enable row level security;

alter table ml_results add column if not exists flag_reason text;
alter table reports    add column if not exists raw jsonb;