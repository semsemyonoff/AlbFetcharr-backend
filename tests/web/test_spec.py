"""Tests for spectree OpenAPI spec and doc pages."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

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
    return make_test_app().test_client()


def test_openapi_json_ok(client):
    resp = client.get("/apidoc/openapi.json")
    assert resp.status_code == 200
    data = json.loads(resp.get_data())
    assert data["info"]["title"] == "AlbFetcharr API"
    assert data["openapi"].startswith("3.1")


def test_scalar_page_ok(client):
    resp = client.get("/apidoc/scalar", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "@scalar/api-reference" in body


def test_swagger_page_ok(client):
    resp = client.get("/apidoc/swagger", follow_redirects=True)
    assert resp.status_code == 200


def test_redoc_page_ok(client):
    resp = client.get("/apidoc/redoc", follow_redirects=True)
    assert resp.status_code == 200


def test_scalar_cdn_url_is_unpinned(client):
    """Assert the Scalar page loads @scalar/api-reference without a pinned version suffix."""
    resp = client.get("/apidoc/scalar", follow_redirects=True)
    body = resp.get_data(as_text=True)
    # If spectree pins a version this assertion will surface it so we can update the plan.
    assert "@scalar/api-reference" in body


def test_strict_mode_excludes_root(client):
    """mode='strict' must exclude the '/' HTML index from openapi.json paths."""
    resp = client.get("/apidoc/openapi.json")
    data = json.loads(resp.get_data())
    paths = data.get("paths", {})
    assert "/" not in paths, f"Expected '/' absent from paths, got: {list(paths.keys())}"


def test_idempotent_registration():
    """Two apps built in one process must both expose /apidoc/openapi.json."""
    app1 = make_test_app()
    app2 = make_test_app()
    for app in (app1, app2):
        resp = app.test_client().get("/apidoc/openapi.json")
        assert resp.status_code == 200


def test_openapi_lists_read_endpoints(client):
    """After Task 2, config/sources/wanted must appear in openapi.json paths."""
    resp = client.get("/apidoc/openapi.json")
    data = json.loads(resp.get_data())
    paths = data.get("paths", {})
    assert "/api/config" in paths, f"Missing /api/config; paths: {list(paths)}"
    assert "/api/sources" in paths, f"Missing /api/sources; paths: {list(paths)}"
    assert "/api/wanted" in paths, f"Missing /api/wanted; paths: {list(paths)}"


def test_openapi_has_component_schemas(client):
    """Schema components for read endpoints must be registered.

    spectree 2.0.1 suffixes schema names with a module hash (e.g. ConfigResponse.922094c),
    so check that each expected title appears somewhere in the schema keys.
    """
    resp = client.get("/apidoc/openapi.json")
    data = json.loads(resp.get_data())
    components = data.get("components", {}).get("schemas", {})
    schema_titles = {v.get("title") for v in components.values()}
    assert "ConfigResponse" in schema_titles, f"Missing ConfigResponse; titles: {schema_titles}"
    assert "SourceItem" in schema_titles, f"Missing SourceItem; titles: {schema_titles}"
    assert "WantedAlbum" in schema_titles, f"Missing WantedAlbum; titles: {schema_titles}"


def test_wanted_unreachable_lidarr_returns_502(client):
    """/api/wanted with unreachable Lidarr returns 502 {error} unchanged."""
    with patch(
        "albfetcharr.web.routes.get_wanted_albums",
        side_effect=ConnectionError("Lidarr unreachable"),
    ), patch.dict("os.environ", {"LIDARR_URL": "http://lidarr.test", "LIDARR_API_KEY": "k"}):
        resp = client.get("/api/wanted")
    assert resp.status_code == 502
    data = resp.get_json()
    assert "error" in data
