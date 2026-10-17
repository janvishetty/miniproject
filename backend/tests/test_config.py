import pytest
from pydantic import ValidationError

from app import config

GOOD = dict(
    SUPABASE_URL="https://abc.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY="super-secret-service-key",
    SUPABASE_ANON_KEY="anon-key-value",
)


def make(**over):
    # _env_file=None -> ignore any real backend/.env during tests
    return config.Settings(_env_file=None, **{**GOOD, **over})


def test_valid_settings_load():
    s = make()
    assert s.cors_origin_list == ["http://localhost:5173"]
    assert not s.is_production


def test_missing_url_is_reported_without_leaking_secrets(monkeypatch):
    # conftest.py sets SUPABASE_URL in the environment; remove it so it is truly missing
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    data = dict(GOOD)
    data.pop("SUPABASE_URL")
    with pytest.raises(ValidationError) as ei:
        config.Settings(_env_file=None, **data)
    text = config.describe_errors(ei.value)
    assert "SUPABASE_URL" in text
    assert "super-secret-service-key" not in text


def test_blank_and_placeholder_keys_rejected():
    for bad in ["", "   ", "PASTE_YOUR_SERVICE_ROLE_KEY_HERE"]:
        with pytest.raises(ValidationError):
            make(SUPABASE_SERVICE_ROLE_KEY=bad)


def test_placeholder_url_rejected():
    with pytest.raises(ValidationError):
        make(SUPABASE_URL="PASTE_YOUR_PROJECT_URL_HERE")


def test_url_with_path_or_query_rejected():
    for bad in ["https://abc.supabase.co/rest/v1/", "https://abc.supabase.co/rest/v1",
                "https://abc.supabase.co/auth/v1", "https://abc.supabase.co?x=1",
                "https://abc.supabase.co#frag", "https:///rest/v1"]:
        with pytest.raises(ValidationError) as ei:
            make(SUPABASE_URL=bad)
        assert "SUPABASE_URL" in config.describe_errors(ei.value)


def test_url_trailing_slash_is_stripped():
    assert make(SUPABASE_URL="https://abc.supabase.co/").SUPABASE_URL == "https://abc.supabase.co"


def test_wildcard_cors_rejected():
    with pytest.raises(ValidationError):
        make(CORS_ORIGINS="*")
    with pytest.raises(ValidationError):
        make(CORS_ORIGINS="http://localhost:5173, *")


def test_secret_not_in_repr():
    s = make()
    assert "super-secret-service-key" not in repr(s)
    assert "super-secret-service-key" not in str(s)
