"""Test helpers: a fake Supabase so tests never touch the real project."""
import os
import uuid
from types import SimpleNamespace

# Set BEFORE the app is imported. Environment variables beat backend/.env.
os.environ.update({
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "APP_ENV": "test",
    "CORS_ORIGINS": "http://localhost:5173",
})

import pytest
from fastapi.testclient import TestClient

from app import config, database, jobs, security
from app.rate_limit import limiter
from app.routers import auth as auth_router


class FakeAuthError(Exception):
    status = 401   # like the real library: an invalid token / credential is a 4xx


class FakeDuplicate(Exception):
    code = "23505"

    def __init__(self):
        super().__init__("duplicate key value violates unique constraint")


class FakeEmailExists(Exception):
    code = "email_exists"

    def __init__(self):
        super().__init__("A user with this email address has already been registered")


class FakeRpcMissing(Exception):
    code = "PGRST202"

    def __init__(self):
        super().__init__("Could not find the function public.set_current_run in the schema cache")


class _Result:
    def __init__(self, data):
        self.data = data
        self.count = None


# Tables whose rows get a generated uuid "id" (like gen_random_uuid() in schema.sql).
_UUID_ID_TABLES = {"pipeline_runs", "incidents", "ml_results", "reports", "dashboard_snapshots"}

# Unique rules: (columns, predicate). Mirrors schema.sql / migration 002 (partial indexes).
_UNIQUE_RULES = {
    "pipeline_runs": [
        (("source_fingerprint",), lambda r: r.get("source_fingerprint") is not None
         and r.get("status") == "completed"),
        (("is_current",), lambda r: bool(r.get("is_current"))),
    ],
    "incidents": [(("pipeline_run_id", "external_id"), lambda r: True)],
}


def _apply_defaults(table, row):
    if table in _UUID_ID_TABLES and "id" not in row:
        row["id"] = str(uuid.uuid4())
    if table == "pipeline_runs":
        row.setdefault("status", "running")
        row.setdefault("is_current", False)
        row.setdefault("trigger", "manual")


def _enforce_unique(table, rows):
    for cols, applies in _UNIQUE_RULES.get(table, []):
        seen = set()
        for r in rows:
            if not applies(r):
                continue
            key = tuple(r.get(c) for c in cols)
            if key in seen:
                raise FakeDuplicate()
            seen.add(key)


class _Query:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.op, self.payload, self.filters, self.n = "select", None, [], None
        self.on_conflict, self.count_mode = None, None
        self.in_filters, self.order_by, self.range_, self.update_values = [], None, None, None

    def in_(self, col, values):
        self.in_filters.append((col, list(values)))
        return self

    def order(self, col, desc=False):
        self.order_by = (col, desc)
        return self

    def range(self, start, end):
        self.range_ = (start, end)
        return self

    def update(self, values):
        self.op, self.update_values = "update", values
        return self

    def _matches(self, r):
        return (all(r.get(c) == v for c, v in self.filters)
                and all(r.get(c) in vals for c, vals in self.in_filters))

    def select(self, *_a, count=None, **_k):
        self.op = "select"
        self.count_mode = count
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def upsert(self, rows, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", rows, on_conflict
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, n):
        self.n = n
        return self

    def execute(self):
        if self.store.fail_tables.get(self.name):
            raise RuntimeError("simulated database outage")
        if self.op == "insert" and self.store.fail_inserts.get(self.name):
            raise RuntimeError("simulated insert failure")
        if self.op == "upsert":
            remaining = self.store.fail_upserts_times.get(self.name, 0)
            if remaining > 0:
                self.store.fail_upserts_times[self.name] = remaining - 1
                raise RuntimeError("simulated transient upsert failure")
        rows = self.store.tables.setdefault(self.name, [])
        if self.op == "insert":
            if self.name == "profiles":
                for r in rows:
                    if r["username"] == self.payload["username"]:
                        raise FakeDuplicate()
            new_row = dict(self.payload)
            _apply_defaults(self.name, new_row)
            rows.append(new_row)
            _enforce_unique(self.name, rows)
            return _Result([dict(new_row)])
        if self.op == "update":
            changed = [r for r in rows if self._matches(r)]
            for r in changed:
                r.update(self.update_values)
            _enforce_unique(self.name, rows)
            return _Result([dict(r) for r in changed])
        if self.op == "upsert":
            incoming = self.payload if isinstance(self.payload, list) else [self.payload]
            key_fields = (self.on_conflict or "").split(",")
            drop = self.store.silent_drop_upserts.get(self.name, 0)   # test hook: stored rows < echoed rows
            written = []
            for n, new_row in enumerate(incoming):
                stored = dict(new_row)
                key = tuple(new_row.get(k) for k in key_fields)
                for i, existing in enumerate(rows):
                    if tuple(existing.get(k) for k in key_fields) == key:
                        if n < len(incoming) - drop:
                            if "id" in existing:
                                stored.setdefault("id", existing["id"])
                            rows[i] = stored
                        break
                else:
                    if n < len(incoming) - drop:
                        _apply_defaults(self.name, stored)
                        rows.append(stored)
                written.append(new_row)
            _enforce_unique(self.name, rows)
            return _Result(written)
        found = [r for r in rows if self._matches(r)]
        if self.order_by:
            col, desc = self.order_by
            found = sorted(found, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        total = len(found)
        if self.range_:
            found = found[self.range_[0]: self.range_[1] + 1]
        elif self.n:
            found = found[: self.n]
        result = _Result(found)
        if self.count_mode:
            result.count = total
        return result


class _Rpc:
    def __init__(self, store, name, params):
        self.store, self.name, self.params = store, name, params

    def execute(self):
        self.store.rpc_calls.append((self.name, dict(self.params)))
        if self.store.fail_rpc == "missing":
            raise FakeRpcMissing()
        if self.store.fail_rpc == "error":
            raise RuntimeError("simulated rpc failure")
        if self.name == "set_current_run":
            runs = self.store.tables.setdefault("pipeline_runs", [])
            target = next((r for r in runs if r.get("id") == self.params.get("run_id")), None)
            if target is None or target.get("status") != "completed":
                raise RuntimeError("pipeline run is not completed")
            for r in runs:                       # same atomic effect as the SQL function
                r["is_current"] = False
            target["is_current"] = True
        return _Result(None)


class FakeSupabase:
    """Acts as admin client, anon client and token verifier at once."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.fail_tables: dict[str, bool] = {}     # every query on the table fails
        self.fail_inserts: dict[str, bool] = {}    # only inserts on the table fail
        self.fail_upserts_times: dict[str, int] = {}  # upsert on the table fails N times, then succeeds
        self.silent_drop_upserts: dict[str, int] = {}  # upsert echoes all rows but stores N fewer (count-mismatch test)
        self.fail_rpc: str | None = None               # None | "missing" | "error"
        self.rpc_calls: list[tuple[str, dict]] = []
        self.users: dict[str, dict] = {}          # id -> {email, password}
        self.auth = SimpleNamespace(
            admin=SimpleNamespace(
                create_user=self._create_user,
                delete_user=self._delete_user,
                sign_out=lambda token: None,
            ),
            sign_in_with_password=self._sign_in,
            get_user=self._get_user,
        )

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        return _Rpc(self, name, params)

    # --- fake auth admin ---
    def _create_user(self, attrs):
        if any(u["email"] == attrs["email"] for u in self.users.values()):
            raise FakeEmailExists()
        uid = str(uuid.uuid4())
        self.users[uid] = {"email": attrs["email"], "password": attrs["password"]}
        return SimpleNamespace(user=SimpleNamespace(id=uid, email=attrs["email"]))

    def _delete_user(self, uid):
        self.users.pop(uid, None)

    # --- fake sign-in / token check ---
    def _sign_in(self, creds):
        for uid, u in self.users.items():
            if u["email"] == creds["email"] and u["password"] == creds["password"]:
                return SimpleNamespace(
                    user=SimpleNamespace(id=uid, email=u["email"]),
                    session=SimpleNamespace(access_token=f"tok-{uid}", expires_in=3600),
                )
        raise FakeAuthError("Invalid login credentials")

    def _get_user(self, token):
        if token.startswith("tok-") and token[4:] in self.users:
            uid = token[4:]
            return SimpleNamespace(user=SimpleNamespace(id=uid, email=self.users[uid]["email"]))
        raise FakeAuthError("invalid JWT")


@pytest.fixture
def fake(monkeypatch):
    f = FakeSupabase()
    monkeypatch.setattr(database, "get_admin_client", lambda: f)
    monkeypatch.setattr(database, "new_anon_client", lambda: f)
    monkeypatch.setattr(database, "get_token_verifier", lambda: f)
    monkeypatch.setattr(auth_router, "AUTH_ERRORS", (FakeAuthError,))
    monkeypatch.setattr(security, "AUTH_ERRORS", (FakeAuthError,))
    return f


@pytest.fixture(autouse=True)
def _reset_jobs():
    jobs.reset()
    yield
    jobs.reset()


@pytest.fixture(autouse=True)
def _limiter_off():
    limiter.reset()
    limiter.enabled = False
    yield
    limiter.reset()
    limiter.enabled = True


@pytest.fixture
def client(fake):
    config.get_settings.cache_clear()
    from app.main import create_app
    # raise_server_exceptions=False so we see the real 500 JSON the user would get
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


VALID = {
    "name": "Test Analyst",
    "username": "TestUser",
    "email": "Test@Example.com",
    "password": "correct-horse-1",
    "position": "Security Analyst",
}


@pytest.fixture
def valid_body():
    return dict(VALID)
