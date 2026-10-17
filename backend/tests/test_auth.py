from app import config
from app.rate_limit import limiter


def register(client, body):
    return client.post("/auth/register", json=body)


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def token_for(client, valid_body):
    register(client, valid_body)
    r = login(client, valid_body["email"], valid_body["password"])
    return r.json()["access_token"]


# ---------------------------- health / basics ----------------------------
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_db_ok(client):
    assert client.get("/health/db").json() == {"status": "ok"}


def test_health_db_down_returns_503_without_details(client, fake):
    fake.fail_tables["pipeline_runs"] = True
    r = client.get("/health/db")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable"}


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ------------------------------ register ------------------------------
def test_register_ok_and_forces_analyst_role(client, fake, valid_body):
    valid_body["role"] = "admin"          # attacker-supplied, must be ignored
    r = register(client, valid_body)
    assert r.status_code == 201
    data = r.json()
    assert data["role"] == "analyst"
    assert data["username"] == "testuser"          # lower-cased
    assert data["email"] == "test@example.com"
    assert "password" not in r.text
    assert fake.tables["profiles"][0]["role"] == "analyst"
    assert any(a["action"] == "auth.register" for a in fake.tables["audit_log"])


def test_register_duplicate_username_409(client, valid_body):
    assert register(client, valid_body).status_code == 201
    valid_body["email"] = "other@example.com"
    assert register(client, valid_body).status_code == 409


def test_register_duplicate_email_409(client, valid_body):
    assert register(client, valid_body).status_code == 201
    valid_body["username"] = "someoneelse"
    assert register(client, valid_body).status_code == 409


def test_register_weak_password_422_and_not_echoed(client, valid_body):
    valid_body["password"] = "Pw1!xyz"          # 7 characters
    r = register(client, valid_body)
    assert r.status_code == 422
    assert "Pw1!xyz" not in r.text               # the rejected value is never echoed
    assert r.json()["error"]["code"] == "validation_error"
    assert all("input" not in d for d in r.json()["error"]["details"])


def test_register_bad_position_422(client, valid_body):
    valid_body["position"] = "Supreme Overlord"
    assert register(client, valid_body).status_code == 422


def test_register_bad_username_422(client, valid_body):
    valid_body["username"] = "bad name!"
    assert register(client, valid_body).status_code == 422


def test_register_rolls_back_auth_user_if_profile_fails(client, fake, valid_body):
    fake.fail_inserts["profiles"] = True
    r = register(client, valid_body)
    assert r.status_code == 503
    assert fake.users == {}               # auth user was removed again


# -------------------------------- login --------------------------------
def test_login_ok(client, valid_body):
    register(client, valid_body)
    r = login(client, "test@example.com", valid_body["password"])
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == 3600
    assert body["profile"]["role"] == "analyst"


def test_login_failures_are_identical(client, valid_body):
    register(client, valid_body)
    wrong_pw = login(client, "test@example.com", "wrong-password")
    no_user = login(client, "nobody@example.com", "wrong-password")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()
    assert wrong_pw.json()["error"]["message"] == "Invalid email or password"


def test_login_supabase_outage_is_503_not_401(client, fake, valid_body):
    from app.routers import auth as auth_router

    # same class the fixture installed as "the library's auth error", plus a 5xx status
    class UpstreamFailure(auth_router.AUTH_ERRORS[0]):
        status = 502

    def boom(_creds):
        raise UpstreamFailure("upstream failure")

    fake.auth.sign_in_with_password = boom
    r = login(client, "test@example.com", valid_body["password"])
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "unavailable"


def test_login_rate_limited(client, valid_body):
    limiter.reset()
    limiter.enabled = True
    codes = [login(client, "x@example.com", "bad-password").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429


# ------------------------- me / roles / logout -------------------------
def test_me_without_token_401(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_tampered_token_401(client, valid_body):
    tok = token_for(client, valid_body)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}x"})
    assert r.status_code == 401


def test_me_with_valid_token_200(client, valid_body):
    tok = token_for(client, valid_body)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["username"] == "testuser"


def test_wrong_auth_scheme_401(client, valid_body):
    tok = token_for(client, valid_body)
    r = client.get("/auth/me", headers={"Authorization": f"Basic {tok}"})
    assert r.status_code == 401


def test_admin_ping_roles(client, fake, valid_body):
    assert client.get("/admin/ping").status_code == 401
    tok = token_for(client, valid_body)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/admin/ping", headers=h).status_code == 403     # analyst
    fake.tables["profiles"][0]["role"] = "admin"                       # promoted in SQL
    r = client.get("/admin/ping", headers=h)
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_logout_ok_and_audited(client, fake, valid_body):
    tok = token_for(client, valid_body)
    r = client.post("/auth/logout", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert any(a["action"] == "auth.logout" for a in fake.tables["audit_log"])


def test_no_password_or_token_in_audit_log(client, fake, valid_body):
    tok = token_for(client, valid_body)
    blob = str(fake.tables["audit_log"])
    assert valid_body["password"] not in blob
    assert tok not in blob


# ------------------------------ production ------------------------------
def test_docs_disabled_in_production(fake, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("APP_ENV", "production")
    config.get_settings.cache_clear()
    try:
        from app.main import create_app
        c = TestClient(create_app(), raise_server_exceptions=False)
        assert c.get("/docs").status_code == 404
        assert c.get("/redoc").status_code == 404
        assert c.get("/openapi.json").status_code == 404
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        config.get_settings.cache_clear()
