-- =====================================================================
-- FSIA / CirionSOC  -  Supabase (PostgreSQL) schema
-- Run this ONCE in: Supabase Dashboard -> SQL Editor -> New query -> Run
-- It is safe to re-run: every statement uses IF NOT EXISTS / OR REPLACE.
--
-- Table groups
--   A. Reference data   : user_devices, threat_indicators
--   B. Events           : raw_events, events
--   C. Pipeline runs    : pipeline_runs
--   D. AI results       : ml_results, rule_alerts, incidents,
--                         incident_events, correlation_results, reports
--   E. App / auth       : profiles, audit_log
--
-- Timestamps: the CSVs have no timezone ("2026-09-01 00:45:54"). We store
-- them as timestamptz and treat them as UTC. Be consistent and it is fine.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Helper: auto-update "updated_at" on every UPDATE
-- ---------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;


-- =====================================================================
-- A. REFERENCE DATA
-- =====================================================================

-- From users_devices.csv  (1031 rows, but only 800 distinct users:
-- one user can own several devices, so the key is user_id + device_id)
create table if not exists user_devices (
  user_id            text not null,
  device_id          text not null,
  registered_device  boolean not null default true,   -- CSV has Y / N
  usual_location     text,
  usual_ip           text,
  secondary_ip       text,
  device_type        text,                            -- android / ios / web
  avg_txn_amount     numeric(14,2),
  primary key (user_id, device_id)
);
create index if not exists idx_user_devices_user on user_devices (user_id);


-- From threat_indicators.csv  (300 rows, ip_address is unique)
create table if not exists threat_indicators (
  ip_address      text primary key,
  indicator_type  text,                               -- IP / PROXY_VPN / TOR_EXIT
  threat_level    text check (threat_level in ('High','Medium','Low')),
  source          text,
  description     text,
  last_seen       date
);


-- =====================================================================
-- B. EVENTS
-- =====================================================================

-- Exact copy of every CSV row, untouched. Our "evidence" copy.
-- If normalisation ever has a bug, we can rebuild "events" from this.
create table if not exists raw_events (
  source_type      text not null check (source_type in ('auth','api','transaction')),
  source_event_id  text not null,                     -- E..., A..., T... exactly as in the CSV
  payload          jsonb not null,                    -- the whole CSV row
  ingested_at      timestamptz not null default now(),
  primary key (source_type, source_event_id)
);


-- One common shape for all three event types.
-- event_id is the ORIGINAL id: E000001 (auth), A000001 (api), T000001 (transaction).
-- The prefixes never clash, so event_id alone is a safe primary key.
-- Columns that don't apply to an event kind are simply NULL.
create table if not exists events (
  event_id      text primary key,
  event_kind    text not null check (event_kind in ('login','logout','api_call','transaction')),
  source_type   text not null check (source_type in ('auth','api','transaction')),
  ts            timestamptz not null,
  user_id       text,
  ip_address    text,
  device_id     text,                                 -- auth + transaction only
  location      text,                                 -- auth + transaction only
  status        text,                                 -- success / failed
  -- auth-only
  mfa_status    text,
  -- api-only
  endpoint      text,
  http_method   text,
  status_code   integer,
  -- transaction-only
  amount        numeric(14,2),
  merchant      text,
  created_at    timestamptz not null default now()
);
create index if not exists idx_events_ts          on events (ts);
create index if not exists idx_events_user_ts     on events (user_id, ts);
create index if not exists idx_events_ip_ts       on events (ip_address, ts);
create index if not exists idx_events_kind        on events (event_kind);


-- =====================================================================
-- C. PIPELINE RUNS
-- Janvi's incident IDs (INC-2026-0081) change on every rerun, so every
-- AI result is tagged with the run that produced it.
-- =====================================================================
create table if not exists pipeline_runs (
  id             uuid primary key default gen_random_uuid(),
  status         text not null default 'running'
                 check (status in ('running','completed','failed')),
  is_current     boolean not null default false,      -- the run the dashboard shows
  trigger        text not null default 'manual',      -- manual / api / scheduled
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  events_scored  integer,
  incident_count integer,
  error_message  text,
  notes          text
);
-- Guarantee that at most ONE run is marked current
create unique index if not exists one_current_run
  on pipeline_runs (is_current) where is_current;


-- =====================================================================
-- D. AI RESULTS
-- =====================================================================

-- Janvi's scored_auth.csv / scored_txn.csv  ->  one row per scored event per run
create table if not exists ml_results (
  id                uuid primary key default gen_random_uuid(),
  pipeline_run_id   uuid not null references pipeline_runs(id) on delete cascade,
  event_id          text not null references events(event_id) on delete cascade,
  anomaly_score     double precision,                 -- 0..1 or 0..100, whatever Janvi outputs
  is_anomalous      boolean not null default false,
  shap_reasons      jsonb,                            -- top features: [{feature, impact, text}]
  unique (pipeline_run_id, event_id)
);
create index if not exists idx_ml_run_score on ml_results (pipeline_run_id, anomaly_score desc);
create index if not exists idx_ml_event     on ml_results (event_id);


-- Aarushi's rule engine output (data/rule_alerts.csv)
-- event_id,rule_id,rule_name,severity,timestamp
create table if not exists rule_alerts (
  id          uuid primary key default gen_random_uuid(),
  event_id    text not null references events(event_id) on delete cascade,
  rule_id     text not null,                          -- R-101
  rule_name   text,
  severity    text check (severity in ('critical','high','medium','low')),
  ts          timestamptz,
  created_at  timestamptz not null default now(),
  unique (event_id, rule_id)
);
create index if not exists idx_rule_alerts_event on rule_alerts (event_id);


-- Janvi's incidents.json  ->  one row per incident per run.
-- Fields that the frontend shows as plain columns are real columns.
-- Nested things (reasons, sequence, timeline, ip_details) stay as JSONB.
create table if not exists incidents (
  id               uuid primary key default gen_random_uuid(),
  pipeline_run_id  uuid not null references pipeline_runs(id) on delete cascade,
  external_id      text not null,                     -- INC-2026-0081 (only unique WITHIN a run)
  severity         text not null check (severity in ('critical','high','medium','low')),
  status           text not null default 'OPEN'
                   check (status in ('OPEN','INVESTIGATING','CONTAINED','RESOLVED')),
  title            text not null,
  asset            text,
  source_ip        text,
  analyst          text not null default 'Unassigned',
  vector           text,                              -- Account Takeover, Brute Force, ...
  confidence       numeric(5,2),                      -- 0-100
  impact           numeric(5,2),                      -- 0-100
  risk_score       numeric(5,2),                      -- drives severity & sorting
  started_at       timestamptz,
  ended_at         timestamptz,
  event_count      integer,
  amount_total     numeric(14,2),
  ip_threat_level  text,
  users            jsonb not null default '[]',
  ips              jsonb not null default '[]',
  ip_details       jsonb not null default '[]',
  reasons          jsonb not null default '[]',
  sequence         jsonb,
  timeline         jsonb not null default '[]',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (pipeline_run_id, external_id)
);
create index if not exists idx_incidents_run_risk on incidents (pipeline_run_id, risk_score desc);
create index if not exists idx_incidents_status   on incidents (status);

drop trigger if exists trg_incidents_updated on incidents;
create trigger trg_incidents_updated
  before update on incidents
  for each row execute function set_updated_at();


-- Which events belong to which incident (the "evidence trail")
create table if not exists incident_events (
  incident_id  uuid not null references incidents(id) on delete cascade,
  event_id     text not null references events(event_id) on delete cascade,
  primary key (incident_id, event_id)
);
create index if not exists idx_incident_events_event on incident_events (event_id);


-- Aarushi's correlation + MITRE output, one row per incident.
-- Shape is deliberately flexible (JSONB) until her module's contract is fixed.
create table if not exists correlation_results (
  id             uuid primary key default gen_random_uuid(),
  incident_id    uuid not null unique references incidents(id) on delete cascade,
  summary        text,
  mitre          jsonb not null default '[]',         -- [{id:"T1110", name:"Brute Force", tactic:"..."}]
  graph          jsonb,                               -- nodes + edges for the attack graph
  related_events jsonb not null default '[]',         -- list of event_ids
  created_at     timestamptz not null default now()
);


-- Janvi's reports.json (LLM report, already grounding-checked)
create table if not exists reports (
  id                    uuid primary key default gen_random_uuid(),
  incident_id           uuid not null unique references incidents(id) on delete cascade,
  summary               text,
  five_ws               jsonb,                        -- {who, what, when, where, why_flagged}
  mitre                 jsonb not null default '[]',
  containment_actions   jsonb not null default '[]',
  investigation_steps   jsonb not null default '[]',
  source                text check (source in ('llm','llm_corrected','template')),
  grounded              boolean not null default false,
  unverified            jsonb not null default '[]',
  created_at            timestamptz not null default now()
);


-- =====================================================================
-- E. APP / AUTH
-- =====================================================================

-- Supabase Auth keeps email + password hash in its own table (auth.users).
-- "profiles" holds the extra fields your login form collects.
create table if not exists profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  full_name   text,
  username    text unique,
  email       text,
  position    text,                                   -- "Security Analyst", "SOC Manager", ...
  role        text not null default 'analyst'
              check (role in ('analyst','manager','admin')),
  created_at  timestamptz not null default now()
);


-- Compliance trail: who did what and when (status changes, copilot questions, ...)
create table if not exists audit_log (
  id          bigint generated always as identity primary key,
  actor_id    uuid,                                   -- profiles.id, null for system actions
  action      text not null,                          -- 'incident.status_changed', 'copilot.ask', ...
  entity      text,                                   -- 'incident', 'report', ...
  entity_id   text,
  details     jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists idx_audit_created on audit_log (created_at desc);


-- =====================================================================
-- SECURITY: Row Level Security
-- We turn RLS ON for every table and add NO policies. That means the
-- public (anon) key can read and write NOTHING. Only our FastAPI server,
-- which uses the secret service_role key, can touch the data.
-- The frontend never talks to the database directly - only to FastAPI.
-- =====================================================================
alter table user_devices         enable row level security;
alter table threat_indicators    enable row level security;
alter table raw_events           enable row level security;
alter table events               enable row level security;
alter table pipeline_runs        enable row level security;
alter table ml_results           enable row level security;
alter table rule_alerts          enable row level security;
alter table incidents            enable row level security;
alter table incident_events      enable row level security;
alter table correlation_results  enable row level security;
alter table reports              enable row level security;
alter table profiles             enable row level security;
alter table audit_log            enable row level security;
