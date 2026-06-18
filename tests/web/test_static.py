"""Tests for static assets and UI branding."""

from albfetcharr.web.app import create_app


def test_static_svg_logo(mocker):
    """GET /static/logo/AlbFetcharr.svg returns 200 with correct content type."""
    mocker.patch("albfetcharr.web.app.bootstrap_default_providers")
    app = create_app()
    client = app.test_client()

    resp = client.get("/static/logo/AlbFetcharr.svg")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.content_type
