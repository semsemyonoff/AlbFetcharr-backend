"""Tests for spectree request validation (422 behavior) on /api/search and /api/download."""

import json
from pathlib import Path
from unittest.mock import patch

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


def test_search_form_content_type_returns_415(client):
    """A form-encoded POST leaves spectree's context.json None → clean 415, not a 500."""
    resp = client.post(
        "/api/search",
        data={"albums": "x"},
        content_type="application/x-www-form-urlencoded",
    )
    assert resp.status_code == 415


# --- album_id coercion ---


def test_search_album_id_string_coerced_to_int(client):
    """Pydantic v2 coerces a numeric string album_id to int; response echoes int."""
    resp = client.post(
        "/api/search",
        data=json.dumps({"albums": [{"artist": "Artist", "title": "Album", "album_id": "5"}]}),
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


# --- /api/download malformed-input tests ---


def test_download_items_not_a_list(client):
    """Sending items as a non-list → 422 (schema validation)."""
    resp = client.post(
        "/api/download",
        data=json.dumps({"items": "not-a-list"}),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_download_form_content_type_returns_415(client):
    """A form-encoded POST leaves spectree's context.json None → clean 415, not a 500."""
    resp = client.post(
        "/api/download",
        data={"items": "x"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 415


def test_download_valid_items_accepted(client):
    """Valid items list with a known source → 202."""
    from albfetcharr.web.routes import download_lock

    payload = {
        "items": [
            {
                "source": "fake",
                "artist": "Artist",
                "title": "Album",
                "match_url": "https://example.com/album",
                "album_id": 1,
            }
        ]
    }
    with patch.dict(
        "os.environ",
        {
            "LIDARR_URL": "http://lidarr.test",
            "LIDARR_API_KEY": "test_key",
            "DOWNLOAD_DIR": "/downloads",
        },
    ):
        resp = client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "started"
    # Wait for the background thread to release the lock before the next test.
    # 15s: the first run imports yt-dlp/ytmusicapi modules lazily (~5–10s cold).
    acquired = download_lock.acquire(timeout=15.0)
    if acquired:
        download_lock.release()


def test_download_quality_string_accepted(client):
    """quality as a string ('2') is accepted via int|str|None union and returns 202."""
    from albfetcharr.web.routes import download_lock

    payload = {
        "items": [
            {
                "source": "fake",
                "artist": "Artist",
                "title": "Album",
                "match_url": "https://example.com/album",
                "album_id": 1,
                "quality": "2",
            }
        ]
    }
    with patch.dict(
        "os.environ",
        {
            "LIDARR_URL": "http://lidarr.test",
            "LIDARR_API_KEY": "test_key",
            "DOWNLOAD_DIR": "/downloads",
        },
    ):
        resp = client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert resp.status_code == 202
    # Wait for the background thread to release the lock before the next test.
    acquired = download_lock.acquire(timeout=15.0)
    if acquired:
        download_lock.release()


# --- /api/download overrides validation tests ---


def test_download_overrides_non_session_key_rejected(client):
    """overrides containing a global-only key (lidarr_url) is rejected → 422."""
    resp = client.post(
        "/api/download",
        data=json.dumps(
            {
                "items": [
                    {
                        "source": "fake",
                        "artist": "A",
                        "title": "B",
                        "match_url": "http://x",
                        "album_id": 1,
                    }
                ],
                "overrides": {"lidarr_url": "http://evil"},
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_download_overrides_unknown_key_rejected(client):
    """overrides containing an unknown/Tier-5 key is rejected → 422."""
    resp = client.post(
        "/api/download",
        data=json.dumps(
            {
                "items": [
                    {
                        "source": "fake",
                        "artist": "A",
                        "title": "B",
                        "match_url": "http://x",
                        "album_id": 1,
                    }
                ],
                "overrides": {"ALBFETCHARR_PORT": "8080"},
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_download_overrides_invalid_value_rejected(client):
    """overrides with a valid session key but an invalid value is rejected → 422.

    The resolver returns raw override strings unchanged, so an invalid value must
    be caught at the request boundary (like PUT) rather than failing the download
    asynchronously after a 202.
    """
    resp = client.post(
        "/api/download",
        data=json.dumps(
            {
                "items": [
                    {
                        "source": "fake",
                        "artist": "A",
                        "title": "B",
                        "match_url": "http://x",
                        "album_id": 1,
                    }
                ],
                "overrides": {"ytdlp_format": "wma"},
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_download_overrides_invalid_int_value_rejected(client):
    """overrides with an out-of-type value for an int session key → 422."""
    resp = client.post(
        "/api/download",
        data=json.dumps(
            {
                "items": [
                    {
                        "source": "fake",
                        "artist": "A",
                        "title": "B",
                        "match_url": "http://x",
                        "album_id": 1,
                    }
                ],
                "overrides": {"ytdlp_quality": "notanint"},
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_download_overrides_session_key_accepted(client):
    """overrides with a valid Tier-3 session key is accepted → 202."""
    from albfetcharr.web.routes import download_lock

    with patch.dict("os.environ", {"DOWNLOAD_DIR": "/downloads"}):
        resp = client.post(
            "/api/download",
            data=json.dumps(
                {
                    "items": [
                        {
                            "source": "fake",
                            "artist": "A",
                            "title": "B",
                            "match_url": "http://x",
                            "album_id": 1,
                        }
                    ],
                    "overrides": {"ytdlp_format": "mp3"},
                }
            ),
            content_type="application/json",
        )
    assert resp.status_code == 202
    acquired = download_lock.acquire(timeout=15.0)
    if acquired:
        download_lock.release()


def test_download_overrides_absent_returns_202(client):
    """Omitting overrides entirely is backward-compatible → 202."""
    from albfetcharr.web.routes import download_lock

    with patch.dict("os.environ", {"DOWNLOAD_DIR": "/downloads"}):
        resp = client.post(
            "/api/download",
            data=json.dumps(
                {
                    "items": [
                        {
                            "source": "fake",
                            "artist": "A",
                            "title": "B",
                            "match_url": "http://x",
                            "album_id": 1,
                        }
                    ],
                }
            ),
            content_type="application/json",
        )
    assert resp.status_code == 202
    acquired = download_lock.acquire(timeout=15.0)
    if acquired:
        download_lock.release()


def test_download_overrides_empty_dict_accepted(client):
    """Empty overrides dict is valid → 202."""
    from albfetcharr.web.routes import download_lock

    with patch.dict("os.environ", {"DOWNLOAD_DIR": "/downloads"}):
        resp = client.post(
            "/api/download",
            data=json.dumps(
                {
                    "items": [
                        {
                            "source": "fake",
                            "artist": "A",
                            "title": "B",
                            "match_url": "http://x",
                            "album_id": 1,
                        }
                    ],
                    "overrides": {},
                }
            ),
            content_type="application/json",
        )
    assert resp.status_code == 202
    acquired = download_lock.acquire(timeout=15.0)
    if acquired:
        download_lock.release()
