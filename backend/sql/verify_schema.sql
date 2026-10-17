-- READ-ONLY checks. Safe to run any time in Supabase -> SQL Editor.
-- Nothing here changes data.

-- 1) Expect 13 rows, rls_enabled = true on every row
select c.relname as table_name, c.relrowsecurity as rls_enabled
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;

-- 2) Expect 0 rows (no policies = only the server's service_role key can read/write)
select tablename, policyname from pg_policies where schemaname = 'public';

-- 3) Expect exactly one row: profiles has a unique username and a role check
select conname, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.profiles'::regclass and contype in ('u','c');

-- 4) After you promote yourself (replace the email), expect role = admin
-- update public.profiles set role = 'admin' where email = 'you@example.com';
-- select id, username, email, role from public.profiles;
