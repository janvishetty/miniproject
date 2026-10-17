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

from app import config, database
from app.rate_limit import limiter
from app.routers import auth as auth_router


class FakeAuthError(Exception):
    pass


class FakeDuplicate(Exception):
    code = "23505"

    def __init__(self):
        super().__init__("duplicate key value violates unique constraint")


class FakeEmailExists(Exception):
    code = "email_exists"

    def __init__(self):
        super().__init__("A user with this email address has already been registered")


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.op, self.payload, self.filters, self.n = "select", None, [], None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
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
        rows = self.store.tables.setdefault(self.name, [])
        if self.op == "insert":
            if self.name == "profiles":
                for r in rows:
                    if r["username"] == self.payload["username"]:
                        raise FakeDuplicate()
            rows.append(dict(self.payload))
            return _Result([self.payload])
        found = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        return _Result(found[: self.n] if self.n else found)


class FakeSupabase:
    """Acts as admin client, anon client and token verifier at once."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.fail_tables: dict[str, bool] = {}     # every query on the table fails
        self.fail_inserts: dict[str, bool] = {}    # only inserts on the table fail
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
    return f


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
