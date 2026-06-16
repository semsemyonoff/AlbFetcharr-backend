"""Tests for static assets and UI branding."""

from pathlib import Path

from albfetcharr.web.app import create_app


def test_static_svg_logo(mocker):
    """GET /static/logo/AlbFetcharr.svg returns 200 with correct content type."""
    mocker.patch("albfetcharr.web.app.bootstrap_default_providers")
    app = create_app()
    client = app.test_client()

    resp = client.get("/static/logo/AlbFetcharr.svg")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.content_type


def test_index_html_contains_albfetcharr_title(mocker):
    """GET / returns HTML with AlbFetcharr in title."""
    import pytest

    dist = Path(__file__).parents[2] / "albfetcharr" / "web" / "static" / "dist" / "index.html"
    if not dist.exists():
        pytest.skip("Frontend not built — build the frontend repo and deploy dist into static/dist")
    mocker.patch("albfetcharr.web.app.bootstrap_default_providers")
    app = create_app()
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<title>AlbFetcharr</title>" in html
    assert "AlbFetcharr" in html
