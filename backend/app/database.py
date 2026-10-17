"""Supabase connections (server-side only).

Three different clients on purpose:

* get_admin_client()    service_role key. Used for ALL database reads/writes and
                        for creating/deleting auth users. Bypasses RLS, so it
                        must never leave the server.
* new_anon_client()     brand-new client per call, anon key. Used ONLY to check
                        an email+password. Signing in changes a client's
                        internal session, so we never do it on the admin client
                        (that would silently turn later queries into "that user's"
                        queries and RLS would block them).
* get_token_verifier()  cached anon client used ONLY for get_user(token).

Other modules call these as `database.get_admin_client()` (module attribute)
so tests can replace them.
"""
from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_admin_client() -> Client:
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY.get_secret_value())


def new_anon_client() -> Client:
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_ANON_KEY.get_secret_value())


@lru_cache
def get_token_verifier() -> Client:
    return new_anon_client()
