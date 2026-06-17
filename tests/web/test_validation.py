"""Tests for spectree request validation (422 behavior) on /api/search."""

import json
from pathlib import Path

import pytest
from flask import Flask

from albfetcharr.sources import clear_registry, register
from albfetcharr.sources.base import Match, SourceProvider
from albfetcharr.web.routes import register_routes
from albfetcharr.web.spec import api


class FakeProvider(SourceProvider):
    id = "fake"
    name = "Fake Provider"

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        return [
            Match(
                source="fake",
                url="https://example.com/album",
                title=album,
                artists=artist,
                cover_url="",
                year=2024,
                track_count=10,
            )
        ]

    def download(self, match: Match, *, quality=None, log=None, on_progress=None) -> bool:
        return True


def make_test_app() -> Flask:
    static_dir = Path(__file__).parent.parent.parent / "albfetcharr" / "web" / "static"
    app = Flask(__name__, static_folder=str(static_dir))
    register_routes(app)
    api.register(app)
    return app


@pytest.fixture
def client():
    clear_registry()
    register(FakeProvider())
    return make_test_app().test_client()


# --- /api/search malformed-input tests ---


def test_search_albums_not_a_list(client):
    resp = client.post(
        "/api/search",
        data=json.dumps({"albums": "not-a-list"}),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_search_album_missing_artist(client):
    resp = client.post(
        "/api/search",
        data=json.dumps({"albums": [{"title": "Album", "album_id": 1}]}),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_search_album_missing_title(client):
    resp = client.post(
        "/api/search",
        data=json.dumps({"albums": [{"artist": "Artist", "album_id": 1}]}),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_search_album_missing_album_id(client):
    resp = client.post(
        "/api/search",
        data=json.dumps({"albums": [{"artist": "Artist", "title": "Album"}]}),
        content_type="application/json",
    )
    assert resp.status_code == 422


# --- album_id coercion ---


def test_search_album_id_string_coerced_to_int(client):
    """Pydantic v2 coerces a numeric string album_id to int; response echoes int."""
    resp = client.post(
        "/api/search",
        data=json.dumps(
            {"albums": [{"artist": "Artist", "title": "Album", "album_id": "5"}]}
        ),
        content_type="application/json",
    )
    # Accepted: pydantic v2 coerces "5" → int 5 in lax mode
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["album_id"] == 5
    assert isinstance(data[0]["album_id"], int)


# --- valid request / 503 tests ---


def test_search_valid_request_unchanged_shape(client):
    """Valid search → 200 with the same response shape as before."""
    resp = client.post(
        "/api/search",
        data=json.dumps(
            {
                "albums": [
                    {
                        "artist": "Artist",
                        "title": "Album",
                        "album_id": 1,
                        "root_folder": "/music",
                    }
                ]
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["artist"] == "Artist"
    assert item["title"] == "Album"
    assert item["album_id"] == 1
    assert item["root_folder"] == "/music"
    assert isinstance(item["results"], list)
    assert isinstance(item["errors"], list)


def test_search_no_providers_returns_503_empty_list():
    """No registered providers → 503 with empty list body (unchanged behavior)."""
    # registry is empty (cleared by _clean_registry autouse fixture)
    app = make_test_app()
    resp = app.test_client().post(
        "/api/search",
        data=json.dumps({"albums": [{"artist": "A", "title": "B", "album_id": 1}]}),
        content_type="application/json",
    )
    assert resp.status_code == 503
    assert resp.get_json() == []
