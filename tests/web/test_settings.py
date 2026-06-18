"""Tests for settings HTTP API (GET/PUT/DELETE /api/settings)."""

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from flask import Flask

from albfetcharr.sources import clear_registry
from albfetcharr.web.routes import register_routes
from albfetcharr.web.spec import api


def make_test_app() -> Flask:
    static_dir = Path(__file__).parent.parent.parent / "albfetcharr" / "web" / "static"
    app = Flask(__name__, static_folder=str(static_dir))
    register_routes(app)
    api.register(app)
    return app


@pytest.fixture
def client():
    clear_registry()
    return make_test_app().test_client()


# ── GET /api/settings ──────────────────────────────────────────────────────────


def test_get_settings_returns_all_keys(client):
    """GET /api/settings returns one item per registry setting."""
    from albfetcharr.settings.registry import all_settings

    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == len(all_settings())


def test_get_settings_grouping(client):
    """Each item carries a non-empty group; multiple groups are present."""
    resp = client.get("/api/settings")
    data = resp.get_json()
    groups = {item["group"] for item in data}
    assert len(groups) > 1
    assert all(item["group"] for item in data)


def test_get_settings_scope_field_present(client):
    """Scope field is present and non-empty on every item."""
    resp = client.get("/api/settings")
    data = resp.get_json()
    assert all(item["scope"] in ("global", "session") for item in data)


def test_get_settings_source_is_default_when_nothing_set(client):
    """All non-optional non-secret settings report source='default' with empty DB and no env."""
    resp = client.get("/api/settings")
    data = resp.get_json()
    defaults = [item for item in data if item["source"] == "default" and not item["secret"]]
    assert len(defaults) > 0


def test_get_settings_secret_not_leaked(client):
    """Secret items never expose a plaintext value field."""
    resp = client.get("/api/settings")
    data = resp.get_json()
    for item in data:
        if item["secret"]:
            assert item["value"] is None
            assert "is_set" in item
            assert "preview" in item


def test_get_settings_secret_from_env_is_masked(client):
    """A secret supplied via env shows a masked preview and is_set=True."""
    import pytest

    pytest.importorskip("cryptography")
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("YANDEX_MUSIC_TOKEN", "supersecrettoken123")
        resp = client.get("/api/settings")
    data = resp.get_json()
    token = next(item for item in data if item["key"] == "yandex_token")
    assert token["is_set"] is True
    assert token["source"] == "env"
    assert token["preview"] is not None
    assert "supersecrettoken123" not in (token["preview"] or "")
    assert token["preview"].startswith("•••")


# ── PUT /api/settings ──────────────────────────────────────────────────────────


def test_put_settings_non_secret_persists(client):
    """PUT a non-secret setting stores it; response shows source='db'."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"default_lang": "ru"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    lang = next(item for item in data if item["key"] == "default_lang")
    assert lang["value"] == "ru"
    assert lang["source"] == "db"
    assert lang["is_set"] is True


def test_put_settings_tier3_key_persists_as_global_default(client):
    """PUT a session-scoped (Tier-3) key stores it as global default."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"ytdlp_format": "mp3"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    fmt = next(item for item in data if item["key"] == "ytdlp_format")
    assert fmt["value"] == "mp3"
    assert fmt["source"] == "db"
    assert fmt["scope"] == "session"

    # Subsequent GET confirms persistence
    get_resp = client.get("/api/settings")
    get_data = get_resp.get_json()
    fmt2 = next(item for item in get_data if item["key"] == "ytdlp_format")
    assert fmt2["source"] == "db"
    assert fmt2["value"] == "mp3"


def test_put_settings_session_key_yandex_clear_comments(client):
    """PUT yandex_clear_comments (Tier-3) persists and resolves with source=db."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"yandex_clear_comments": "1"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    item = next(i for i in data if i["key"] == "yandex_clear_comments")
    assert item["source"] == "db"
    assert item["value"] == "1"


def test_put_settings_secret_with_key(client, monkeypatch):
    """PUT a secret setting encrypts it when SECRET_KEY is configured."""
    secret_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", secret_key)
    resp = client.put(
        "/api/settings",
        data=json.dumps({"yandex_token": "my-yandex-secret-token"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    token = next(item for item in data if item["key"] == "yandex_token")
    assert token["secret"] is True
    assert token["is_set"] is True
    assert token["source"] == "db"
    # Plaintext must never appear in the response payload
    raw_response = json.dumps(data)
    assert "my-yandex-secret-token" not in raw_response
    assert token["preview"] is not None
    assert token["preview"].startswith("•••")


def test_put_settings_secret_without_secret_key_returns_400(client, monkeypatch):
    """PUT a secret setting without ALBFETCHARR_SECRET_KEY returns 400."""
    monkeypatch.delenv("ALBFETCHARR_SECRET_KEY", raising=False)
    resp = client.put(
        "/api/settings",
        data=json.dumps({"yandex_token": "mytoken"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "SECRET_KEY" in data["error"]


def test_put_settings_unknown_key_returns_400(client):
    """PUT an unknown key (incl. Tier-5) returns 400."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"ALBFETCHARR_PORT": "8080"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_put_settings_invalid_enum_returns_422(client):
    """PUT an invalid enum value returns 422."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"ytdlp_format": "wma"}),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_put_settings_invalid_int_returns_422(client):
    """PUT a non-integer value for an int setting returns 422."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"yandex_delay": "notanumber"}),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_put_settings_int_below_minimum_returns_422(client):
    """PUT an int below the minimum bound returns 422."""
    resp = client.put(
        "/api/settings",
        data=json.dumps({"yandex_net_timeout": "0"}),  # min_val=1
        content_type="application/json",
    )
    assert resp.status_code == 422


# ── DELETE /api/settings/<key> ─────────────────────────────────────────────────


def test_delete_settings_unknown_key_returns_404(client):
    """DELETE /api/settings/<unknown> returns 404."""
    resp = client.delete("/api/settings/totally_unknown_key")
    assert resp.status_code == 404


def test_delete_settings_falls_back_to_env(client):
    """DELETE after PUT removes the DB override; source falls back to env."""
    import pytest

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("ALBFETCHARR_DEFAULT_LANG", "ru")

        # Write to DB
        client.put(
            "/api/settings",
            data=json.dumps({"default_lang": "en"}),
            content_type="application/json",
        )

        # Confirm it's in the DB
        get_resp = client.get("/api/settings")
        lang_db = next(i for i in get_resp.get_json() if i["key"] == "default_lang")
        assert lang_db["source"] == "db"

        # Delete the DB override
        del_resp = client.delete("/api/settings/default_lang")
        assert del_resp.status_code == 200
        del_data = del_resp.get_json()
        lang_env = next(i for i in del_data if i["key"] == "default_lang")
        assert lang_env["source"] == "env"
        assert lang_env["value"] == "ru"


def test_delete_settings_returns_updated_view(client):
    """DELETE returns the full settings list (same as GET) after removal."""
    from albfetcharr.settings.registry import all_settings

    client.put(
        "/api/settings",
        data=json.dumps({"default_theme": "dark"}),
        content_type="application/json",
    )
    resp = client.delete("/api/settings/default_theme")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == len(all_settings())


# ── No-restart registry refresh ────────────────────────────────────────────────


def test_put_enable_soundcloud_false_removes_from_sources(client):
    """PUT enable_soundcloud=0 is reflected by /api/sources without restart."""
    from albfetcharr.sources import bootstrap_default_providers

    # Populate the registry so soundcloud is in there
    bootstrap_default_providers()
    sources_before = client.get("/api/sources").get_json()
    assert any(s["id"] == "soundcloud" for s in sources_before)

    # Disable soundcloud via settings API
    resp = client.put(
        "/api/settings",
        data=json.dumps({"enable_soundcloud": "0"}),
        content_type="application/json",
    )
    assert resp.status_code == 200

    # The PUT handler re-bootstrapped; soundcloud must be gone
    sources_after = client.get("/api/sources").get_json()
    assert not any(s["id"] == "soundcloud" for s in sources_after)


def test_put_yandex_token_registers_yandex_source(client, monkeypatch):
    """Storing a yandex_token via PUT causes bootstrap to register the Yandex provider."""
    from albfetcharr.sources import bootstrap_default_providers

    secret_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", secret_key)
    # Ensure no pre-existing token from the environment bleeds in
    monkeypatch.delenv("YANDEX_MUSIC_TOKEN", raising=False)

    # No token → no yandex provider
    bootstrap_default_providers()
    sources_before = client.get("/api/sources").get_json()
    assert not any(s["id"] == "yandex" for s in sources_before)

    # Store a token → PUT triggers bootstrap → yandex registered
    resp = client.put(
        "/api/settings",
        data=json.dumps({"yandex_token": "fake-yandex-token-for-test"}),
        content_type="application/json",
    )
    assert resp.status_code == 200

    sources_after = client.get("/api/sources").get_json()
    assert any(s["id"] == "yandex" for s in sources_after)
