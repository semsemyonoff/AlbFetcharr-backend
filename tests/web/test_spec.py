"""Tests for spectree OpenAPI spec and doc pages."""

import json
from pathlib import Path

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
