"""Tests for AlbFetcharr web API routes."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses
from flask import Flask

from albfetcharr.sources import clear_registry, register
from albfetcharr.sources.base import DownloadProgress, Match, SourceProvider
from albfetcharr.web.routes import register_routes
from albfetcharr.web.spec import api


def _collect_stream_events(test_client, payload, env=None):
    """Start a download and drain the SSE stream into a list of parsed events."""
    test_client.post("/api/download/stream/claim")
    env = env or {
        "LIDARR_URL": "http://lidarr.test",
        "LIDARR_API_KEY": "test_key",
        "DOWNLOAD_DIR": "/downloads",
    }
    with patch.dict("os.environ", env):
        test_client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )
        stream_response = test_client.get("/api/download/stream")
    events = []
    for line in stream_response.get_data(as_text=True).split("\n"):
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


class FakeProvider(SourceProvider):
    """Fake provider for testing."""

    id = "yandex"
    name = "Fake Yandex Music"

    def __init__(self):
        self._options = MagicMock(quality="2")

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        return [
            Match(
                source="yandex",
                url=f"https://music.yandex.ru/album/{artist}/{album}",
                title=album,
                artists=artist,
                cover_url="https://fake.com/cover.jpg",
                year=2024,
                track_count=10,
            )
        ]

    def download(
        self, match: Match, *, quality: str | None = None, log=None, on_progress=None
    ) -> bool:
        if log:
            log("Fake download started")
            log("Fake download completed")
        return True


class FakeYouTubeProvider(SourceProvider):
    """Fake YouTube Music provider for testing."""

    id = "youtube_music"
    name = "Fake YouTube Music"

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        return [
            Match(
                source="youtube_music",
                url=f"https://music.youtube.com/playlist?list={artist}-{album}",
                title=f"{album} (YouTube)",
                artists=artist,
                cover_url="https://fake.com/yt_cover.jpg",
                year=2024,
                track_count=8,
            )
        ]

    def download(
        self, match: Match, *, quality: str | None = None, log=None, on_progress=None
    ) -> bool:
        if log:
            log("Fake YouTube download started")
            log("Fake YouTube download completed")
        return True


class FakeBrokenProvider(SourceProvider):
    """Fake provider that raises errors for testing error isolation."""

    id = "broken"
    name = "Broken Provider"

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        raise RuntimeError("Simulated search failure")

    def download(
        self, match: Match, *, quality: str | None = None, log=None, on_progress=None
    ) -> bool:
        return False


def make_test_app() -> Flask:
    """Create Flask app without bootstrap for testing."""
    static_dir = Path(__file__).parent.parent.parent / "albfetcharr" / "web" / "static"
    app = Flask(
        __name__,
        static_folder=str(static_dir),
    )
    register_routes(app)
    api.register(app)
    return app


@pytest.fixture
def client():
    """Provide test client with FakeProvider registered."""
    clear_registry()
    register(FakeProvider())
    app = make_test_app()
    return app.test_client()


@pytest.mark.usefixtures("_clean_registry")
def test_api_health_ok(client):
    """/api/health is a dependency-free 200 liveness probe."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


@pytest.mark.usefixtures("_clean_registry")
@responses.activate
def test_api_config(client):
    """Test /api/config endpoint returns default quality."""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.get_json()
    assert "default_quality" in data


@pytest.mark.usefixtures("_clean_registry")
def test_api_config_returns_ui_defaults(client):
    """Test /api/config endpoint returns UI defaults (lang and theme)."""
    with patch.dict(
        "os.environ",
        {
            "ALBFETCHARR_DEFAULT_LANG": "ru",
            "ALBFETCHARR_DEFAULT_THEME": "dark",
        },
    ):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.get_json()
        assert "default_lang" in data
        assert "default_theme" in data
        assert data["default_lang"] == "ru"
        assert data["default_theme"] == "dark"
        assert "import_enabled" in data


@pytest.mark.usefixtures("_clean_registry")
def test_api_config_encryption_disabled(client, monkeypatch):
    """encryption_enabled is false when ALBFETCHARR_SECRET_KEY is unset."""
    monkeypatch.delenv("ALBFETCHARR_SECRET_KEY", raising=False)
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.get_json()
    assert data["encryption_enabled"] is False


@pytest.mark.usefixtures("_clean_registry")
def test_api_config_encryption_enabled(client, monkeypatch):
    """encryption_enabled is true when ALBFETCHARR_SECRET_KEY holds a valid Fernet key."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", Fernet.generate_key().decode())
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.get_json()
    assert data["encryption_enabled"] is True


@pytest.mark.usefixtures("_clean_registry")
def test_api_sources(client):
    """Test /api/sources endpoint returns registered providers."""
    response = client.get("/api/sources")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == "yandex"
    assert data[0]["name"] == "Fake Yandex Music"


@pytest.mark.usefixtures("_clean_registry")
@responses.activate
def test_api_wanted(client, tmp_path):
    """Test /api/wanted endpoint with mocked Lidarr."""
    responses.add(
        responses.GET,
        "http://lidarr.test/api/v1/wanted/missing",
        json={
            "records": [
                {
                    "id": 1,
                    "artist": {"id": 10, "artistName": "Artist One"},
                    "title": "Album One",
                    "releaseDate": "2024-01-01",
                }
            ],
            "totalRecords": 1,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "http://lidarr.test/api/v1/rootfolder",
        json=[{"id": 1, "path": "/music"}],
        status=200,
    )
    responses.add(
        responses.GET,
        "http://lidarr.test/api/v1/artist",
        json=[{"id": 10, "path": "/music/Artist One"}],
        status=200,
    )
    responses.add(
        responses.GET,
        "http://lidarr.test/api/v1/track",
        json=[{"id": i} for i in range(10)],
        status=200,
    )

    with patch.dict(
        "os.environ",
        {
            "LIDARR_URL": "http://lidarr.test",
            "LIDARR_API_KEY": "test_key",
            "DOWNLOAD_DIR": str(tmp_path),
        },
    ):
        response = client.get("/api/wanted")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "artist" in data[0]
        assert "title" in data[0]
        assert "status" in data[0]


@pytest.mark.usefixtures("_clean_registry")
@responses.activate
def test_api_search(client):
    """Test /api/search endpoint with mocked provider."""
    payload = {
        "albums": [
            {
                "artist": "Artist One",
                "title": "Album One",
                "album_id": 1,
                "root_folder": "/music",
            }
        ]
    }

    response = client.post(
        "/api/search",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["artist"] == "Artist One"
    assert len(data[0]["results"]) > 0
    assert "match_url" in data[0]["results"][0]
    assert data[0]["results"][0]["source"] == "yandex"
    assert data[0]["results"][0]["source_name"] == "Fake Yandex Music"
    assert "errors" in data[0]
    assert isinstance(data[0]["errors"], list)


@pytest.mark.usefixtures("_clean_registry")
@responses.activate
def test_api_search_multi_source(client):
    """Test /api/search with multiple sources."""
    clear_registry()
    register(FakeProvider())
    register(FakeYouTubeProvider())
    app = make_test_app()
    test_client = app.test_client()

    payload = {
        "albums": [
            {
                "artist": "Artist One",
                "title": "Album One",
                "album_id": 1,
                "root_folder": "/music",
            }
        ],
        "sources": ["yandex", "youtube_music"],
    }

    response = test_client.post(
        "/api/search",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    album = data[0]
    assert len(album["results"]) == 2
    sources_found = {r["source"] for r in album["results"]}
    assert sources_found == {"yandex", "youtube_music"}
    assert all("match_url" in r and "source_name" in r for r in album["results"])


@pytest.mark.usefixtures("_clean_registry")
@responses.activate
def test_api_search_error_isolation(client):
    """Test /api/search with error isolation per provider."""
    clear_registry()
    register(FakeProvider())
    register(FakeBrokenProvider())
    app = make_test_app()
    test_client = app.test_client()

    payload = {
        "albums": [
            {
                "artist": "Artist One",
                "title": "Album One",
                "album_id": 1,
                "root_folder": "/music",
            }
        ],
    }

    response = test_client.post(
        "/api/search",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    album = data[0]
    assert len(album["results"]) == 1
    assert album["results"][0]["source"] == "yandex"
    assert len(album["errors"]) == 1
    assert album["errors"][0]["source"] == "broken"
    assert "message" in album["errors"][0]


@pytest.mark.usefixtures("_clean_registry")
def test_api_download_started(client):
    """Test /api/download endpoint starts download."""

    payload = {
        "items": [
            {
                "artist": "Artist One",
                "title": "Album One",
                "album_id": 1,
                "source": "yandex",
                "match_url": "https://music.yandex.ru/album/1",
                "match_title": "Album One",
                "match_artists": "Artist One",
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
        response = client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert response.status_code == 202
        data = response.get_json()
        assert data["status"] == "started"


@pytest.mark.usefixtures("_clean_registry")
def test_api_download_missing_source(client):
    """Test /api/download returns 422 (schema validation) when source is missing."""

    payload = {
        "items": [
            {
                "artist": "Artist One",
                "title": "Album One",
                "album_id": 1,
                "match_url": "https://music.yandex.ru/album/1",
                "match_title": "Album One",
                "match_artists": "Artist One",
            }
        ]
    }

    response = client.post(
        "/api/download",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("_clean_registry")
def test_api_download_unknown_source(client):
    """Test /api/download returns 400 when source is unknown."""

    payload = {
        "items": [
            {
                "artist": "Artist One",
                "title": "Album One",
                "album_id": 1,
                "source": "unknown_source",
                "match_url": "https://music.yandex.ru/album/1",
                "match_title": "Album One",
                "match_artists": "Artist One",
            }
        ]
    }

    response = client.post(
        "/api/download",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "unknown source" in data["error"].lower()


@pytest.mark.usefixtures("_clean_registry")
def test_api_download_already_running(client):
    """Test /api/download returns 409 if already running."""
    from albfetcharr.web.routes import download_lock

    payload = {"items": []}

    with download_lock:
        response = client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert response.status_code == 409
        data = response.get_json()
        assert "error" in data


@pytest.mark.usefixtures("_clean_registry")
def test_api_download_passes_lidarr_names_to_provider():
    """The Match handed to provider.download must carry the Lidarr album/artist names
    (item title/artist), not the source's own match metadata, so the on-disk layout
    keys off the names find_album_dir/check_album_status look albums up by. The source
    identifier still travels via url=match_url.
    """
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    captured: list[Match] = []

    class CapturingProvider(SourceProvider):
        id = "youtube_music"
        name = "Capturing Provider"

        def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
            return []

        def download(
            self, match: Match, *, quality: str | None = None, log=None, on_progress=None
        ) -> bool:
            captured.append(match)
            if log:
                log("captured")
            return True

    clear_registry()
    register(CapturingProvider())
    app = make_test_app()
    test_client = app.test_client()

    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                # Lidarr names (the on-disk identity we must use)
                "artist": "Lidarr Artist",
                "title": "Lidarr Album",
                "album_id": 1,
                "source": "youtube_music",
                # source identifier travels via match_url
                "match_url": "https://music.youtube.com/browse/MPREb_abc123",
                # source metadata deliberately DIFFERENT from the Lidarr names
                "match_title": "Various Artists - Album (Remastered)",
                "match_artists": "Various Artists",
                "quality": None,
            }
        ]
    }

    # Force per-run providers empty so the global registry CapturingProvider is used.
    # This test checks the Match construction, not the per-run vs registry selection.
    with patch("albfetcharr.web.routes._build_per_run_providers", return_value={}):
        with patch.dict(
            "os.environ",
            {
                "LIDARR_URL": "http://lidarr.test",
                "LIDARR_API_KEY": "test_key",
                "DOWNLOAD_DIR": "/downloads",
            },
        ):
            response = test_client.post(
                "/api/download",
                data=json.dumps(payload),
                content_type="application/json",
            )
            assert response.status_code == 202
            # Reading the SSE stream blocks until the background download completes.
            test_client.get("/api/download/stream").get_data(as_text=True)

    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None

    assert len(captured) == 1
    match = captured[0]
    # Lidarr names, NOT the source's match_title/match_artists.
    assert match.title == "Lidarr Album"
    assert match.artists == "Lidarr Artist"
    # url still carries the source identifier used to resolve the download.
    assert match.url == "https://music.youtube.com/browse/MPREb_abc123"


@pytest.mark.usefixtures("_clean_registry")
def test_api_download_stream(client):
    """Test /api/download/stream endpoint."""
    response = client.get("/api/download/stream")
    assert response.status_code == 200
    assert "text/event-stream" in response.content_type


@pytest.mark.usefixtures("_clean_registry")
def test_stream_claim_returns_409_when_held(client):
    """Test /api/download/stream/claim returns 409 when stream is held."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    # First claim should succeed
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 200
    data = response.get_json()
    assert data["claimed"] is True

    # Second claim should fail
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 409
    data = response.get_json()
    assert "error" in data
    assert data["error"] == "stream already in use"

    # Clean up for other tests
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_stream_claim_drains_stale_queue_items(client):
    """Test claim endpoint drains stale queue items from crashed session."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state, log_queue

    # Pre-populate queue with stale items
    log_queue.put("stale log line")
    log_queue.put({"progress": {"album_id": 1, "status": "starting"}})
    assert not log_queue.empty()

    # Claim should drain the queue
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 200

    # Queue should be empty after claim
    assert log_queue.empty()

    # Clean up
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_stream_claim_expires_after_idle(client):
    """Test claim auto-releases after 60s of no last_seen update."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    # First claim succeeds
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 200

    # Simulate 60+ seconds idle by directly manipulating state
    with _stream_claim_lock:
        now = time.monotonic()
        _stream_claim_state["last_seen"] = now - 61

    # Second claim should now succeed (auto-released)
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 200

    # Clean up
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_stream_claim_reconnect_takes_over_held_claim(client):
    """Reconnect claim succeeds even when the claim is held, and increments generation."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    # First claim
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 200
    with _stream_claim_lock:
        gen_after_first = _stream_claim_state["generation"]

    # Second claim (no reconnect) must still return 409
    response = client.post("/api/download/stream/claim")
    assert response.status_code == 409

    # Reconnect claim must succeed even while first claim is held
    response = client.post(
        "/api/download/stream/claim",
        json={"reconnect": True},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["claimed"] is True

    # Generation must have been incremented so the old generator's finally is a no-op
    with _stream_claim_lock:
        assert _stream_claim_state["generation"] > gen_after_first


@pytest.mark.usefixtures("_clean_registry")
def test_handoffs_pending_decremented_on_client_disconnect():
    """GeneratorExit (client disconnect mid-stream) must not leak handoffs_pending.

    If handoffs_pending stays elevated after disconnect, a reconnecting owner
    that receives None will spin forever waiting for the counter to reach zero.
    """
    from albfetcharr.web.app import create_app
    from albfetcharr.web.routes import (
        _handoff_condition,
        _stream_claim_lock,
        _stream_claim_state,
        log_queue,
    )

    app = create_app()
    test_client = app.test_client()

    test_client.post("/api/download/stream/claim")

    # Put a regular message so the generator yields it (no sentinel — we will
    # disconnect before the stream completes naturally).
    log_queue.put("test message")

    with app.test_request_context("/api/download/stream"):
        stream_resp = app.view_functions["api_download_stream"]()

    gen = iter(stream_resp.response)

    # Advance to the first yielded chunk (the regular message yield).
    # The generator is now suspended inside the try/finally block with
    # handoffs_pending == 1.
    next(gen)

    # Simulate client disconnect: raises GeneratorExit inside the generator.
    gen.close()

    # handoffs_pending must be 0; if it remains 1 a reconnecting owner would
    # wait indefinitely when it drains the queue after receiving None.
    with _handoff_condition:
        assert _stream_claim_state["handoffs_pending"] == 0

    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_stream_handoff_coordination_prevents_orphaned_messages(client):
    """New generator waits for in-flight stale handoffs before closing.

    Race scenario: stale generator pops message A, new generator pops sentinel
    None concurrently.  The new generator could close before stale finishes its
    appendleft, orphaning A.  The handoffs_pending counter (incremented before
    get(), decremented after appendleft) ensures the new generator waits.

    Simulated here by: pre-incrementing handoffs_pending to mimic a stale
    generator mid-handoff, then letting a background thread do the appendleft
    and decrement (simulating the stale generator finishing) while the new
    generator's SSE stream is blocking in the handoffs_pending wait.
    """
    from albfetcharr.web.app import create_app
    from albfetcharr.web.routes import (
        _handoff_condition,
        _stream_claim_lock,
        _stream_claim_state,
        log_queue,
    )

    app = create_app()
    test_client = app.test_client()

    # Claim the stream (fresh — queue is drained, handoffs_pending reset to 0)
    response = test_client.post("/api/download/stream/claim")
    assert response.status_code == 200

    progress_event = {"progress": {"album_id": 42, "status": "done"}}

    # Pre-increment handoffs_pending: mimics a stale generator that has
    # entered get() and is about to appendleft a message.
    with _handoff_condition:
        _stream_claim_state["handoffs_pending"] += 1

    # Only put the sentinel in the queue.  The progress event will be
    # appendleft'd by the background thread below, simulating the stale
    # generator completing its handoff while the new generator is waiting.
    log_queue.put(None)

    def simulate_stale_handoff():
        # Give the new generator time to pop None and enter the wait.
        time.sleep(0.05)
        with log_queue.mutex:
            log_queue.queue.appendleft(progress_event)
            log_queue.not_empty.notify()
        with _handoff_condition:
            _stream_claim_state["handoffs_pending"] -= 1
            _handoff_condition.notify_all()

    handoff_thread = threading.Thread(target=simulate_stale_handoff, daemon=True)
    handoff_thread.start()

    stream_response = test_client.get("/api/download/stream")
    handoff_thread.join(timeout=5)

    raw = stream_response.get_data(as_text=True)
    data_lines = [line[6:] for line in raw.split("\n") if line.startswith("data: ")]
    events = []
    for line in data_lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    progress_events = [e for e in events if "progress" in e]
    done_events = [e for e in events if e.get("done")]

    assert len(progress_events) == 1, "progress event requeued by stale generator must be emitted"
    assert progress_events[0] == progress_event
    assert len(done_events) == 1, "done event must be emitted"

    progress_idx = next(i for i, e in enumerate(events) if "progress" in e)
    done_idx = next(i for i, e in enumerate(events) if e.get("done"))
    assert progress_idx < done_idx, "progress must precede done"

    # Cleanup: clear claim state so the fixture reset works cleanly
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_download_stream_emits_progress(client):
    """Test /api/download/stream emits canonical progress events."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    # Create a provider that succeeds
    class SuccessProvider(SourceProvider):
        id = "test"
        name = "Test Provider"

        def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
            return []

        def download(
            self, match: Match, *, quality: str | None = None, log=None, on_progress=None
        ) -> bool:
            if log:
                log("Download success")
            return True

    clear_registry()
    register(SuccessProvider())
    app = make_test_app()
    test_client = app.test_client()

    # Claim the stream first
    claim_response = test_client.post("/api/download/stream/claim")
    assert claim_response.status_code == 200

    # Start a download
    payload = {
        "items": [
            {
                "artist": "Test Artist",
                "title": "Test Album",
                "album_id": 123,
                "source": "test",
                "match_url": "https://test.com/album",
                "match_title": "Test Album",
                "match_artists": "Test Artist",
                "quality": None,
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
        response = test_client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert response.status_code == 202

        # Open SSE stream and collect events
        stream_response = test_client.get("/api/download/stream")
        events = []
        for line in stream_response.get_data(as_text=True).split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    events.append(event)
                except json.JSONDecodeError:
                    pass

    # Verify progress events are present
    progress_events = [e for e in events if "progress" in e]
    assert len(progress_events) > 0

    # Check canonical shape of first progress event
    first_progress = progress_events[0]["progress"]
    assert "album_id" in first_progress
    assert "item_index" in first_progress
    assert "item_total" in first_progress
    assert "status" in first_progress
    assert "message" in first_progress

    # Verify status transitions
    statuses = [e["progress"]["status"] for e in progress_events]
    assert "starting" in statuses
    assert "downloading" in statuses
    assert "downloaded" in statuses or "done" in statuses

    # Clean up
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_download_stream_legacy_log_strings_still_work(client):
    """Test /api/download/stream still emits legacy log strings."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class TestProvider(SourceProvider):
        id = "test"
        name = "Test Provider"

        def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
            return []

        def download(
            self, match: Match, *, quality: str | None = None, log=None, on_progress=None
        ) -> bool:
            if log:
                log("Custom log message from provider")
            return True

    clear_registry()
    register(TestProvider())
    app = make_test_app()
    test_client = app.test_client()

    # Claim the stream
    test_client.post("/api/download/stream/claim")

    # Start download
    payload = {
        "items": [
            {
                "artist": "Artist",
                "title": "Album",
                "album_id": 1,
                "source": "test",
                "match_url": "https://test.com",
                "match_title": "Album",
                "match_artists": "Artist",
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
        test_client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Collect SSE events
        stream_response = test_client.get("/api/download/stream")
        events = []
        for line in stream_response.get_data(as_text=True).split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    events.append(event)
                except json.JSONDecodeError:
                    pass

    # Verify log events exist
    log_events = [e for e in events if "log" in e]
    assert len(log_events) > 0

    # Clean up
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_importing_status_emitted_per_album_at_batch_boundary(client):
    """Test importing status emitted per album when import_path is set."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class TestProvider(SourceProvider):
        id = "test"
        name = "Test Provider"

        def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
            return []

        def download(
            self, match: Match, *, quality: str | None = None, log=None, on_progress=None
        ) -> bool:
            return True

    clear_registry()
    register(TestProvider())
    app = make_test_app()
    test_client = app.test_client()

    # Claim the stream
    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "artist": "Artist 1",
                "title": "Album 1",
                "album_id": 1,
                "source": "test",
                "match_url": "https://test.com/1",
                "match_title": "Album 1",
                "match_artists": "Artist 1",
            },
            {
                "artist": "Artist 2",
                "title": "Album 2",
                "album_id": 2,
                "source": "test",
                "match_url": "https://test.com/2",
                "match_title": "Album 2",
                "match_artists": "Artist 2",
            },
        ]
    }

    with (
        patch.dict(
            "os.environ",
            {
                "LIDARR_URL": "http://lidarr.test",
                "LIDARR_API_KEY": "test_key",
                "DOWNLOAD_DIR": "/downloads",
                "ALBFETCHARR_LIDARR_IMPORT_PATH": "/music/import",
            },
        ),
        patch("albfetcharr.web.routes.run_import", return_value=True),
        patch("albfetcharr.web.routes.post_import_cleanup"),
    ):
        test_client.post(
            "/api/download",
            data=json.dumps(payload),
            content_type="application/json",
        )

        stream_response = test_client.get("/api/download/stream")
        events = []
        for line in stream_response.get_data(as_text=True).split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    events.append(event)
                except json.JSONDecodeError:
                    pass

    progress_events = [e for e in events if "progress" in e]
    importing_events = [e for e in progress_events if e["progress"]["status"] == "importing"]

    # Should have importing events for both albums
    assert len(importing_events) == 2
    importing_album_ids = {e["progress"]["album_id"] for e in importing_events}
    assert importing_album_ids == {1, 2}

    # Clean up
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_done_emitted_directly_when_import_path_unset(client):
    """Test done status emitted directly (no importing) when import_path unset."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class TestProvider(SourceProvider):
        id = "test"
        name = "Test Provider"

        def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
            return []

        def download(
            self, match: Match, *, quality: str | None = None, log=None, on_progress=None
        ) -> bool:
            return True

    clear_registry()
    register(TestProvider())
    app = make_test_app()
    test_client = app.test_client()

    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "artist": "Artist",
                "title": "Album",
                "album_id": 1,
                "source": "test",
                "match_url": "https://test.com",
                "match_title": "Album",
                "match_artists": "Artist",
            }
        ]
    }

    with patch("albfetcharr.web.routes.resolve_app_config") as mock_resolve:
        mock_app_cfg = MagicMock()
        mock_app_cfg.lidarr.base_url = "http://lidarr.test"
        mock_app_cfg.lidarr.api_key = "test_key"
        mock_app_cfg.lidarr.import_path = ""
        mock_app_cfg.yandex_options.clear_comments = False
        mock_resolve.return_value = mock_app_cfg

        with patch.dict(
            "os.environ",
            {
                "LIDARR_URL": "http://lidarr.test",
                "LIDARR_API_KEY": "test_key",
                "DOWNLOAD_DIR": "/downloads",
            },
        ):
            test_client.post(
                "/api/download",
                data=json.dumps(payload),
                content_type="application/json",
            )

            stream_response = test_client.get("/api/download/stream")
            events = []
            for line in stream_response.get_data(as_text=True).split("\n"):
                if line.startswith("data: "):
                    try:
                        event = json.loads(line[6:])
                        events.append(event)
                    except json.JSONDecodeError:
                        pass

    progress_events = [e for e in events if "progress" in e]
    importing_events = [e for e in progress_events if e["progress"]["status"] == "importing"]
    done_events = [e for e in progress_events if e["progress"]["status"] == "done"]

    # Should have no importing events
    assert len(importing_events) == 0

    # Should have done events
    assert len(done_events) > 0

    # Verify the done message mentions import disabled
    log_events = [e for e in events if "log" in e]
    log_messages = [e["log"] for e in log_events]
    assert any("import disabled" in msg.lower() for msg in log_messages), (
        f"Log messages: {log_messages}"
    )

    # Clean up
    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_download_emits_numeric_per_track_progress(client):
    """A provider reporting on_progress yields downloading events with a numeric
    `progress` and per-track index/total so the UI can render a real bar."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class TrackProvider(SourceProvider):
        id = "test"
        name = "Test Provider"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            total = 4
            for i in range(1, total + 1):
                on_progress(
                    DownloadProgress(completed=i, total=total, downloaded=i, message=f"t{i}")
                )
            return True

    clear_registry()
    register(TrackProvider())
    test_client = make_test_app().test_client()

    payload = {
        "items": [
            {
                "artist": "Artist",
                "title": "Album",
                "album_id": 7,
                "source": "test",
                "match_url": "https://test.com",
            }
        ]
    }
    events = _collect_stream_events(test_client, payload)

    progress_events = [e["progress"] for e in events if "progress" in e]
    track_events = [p for p in progress_events if p.get("track_total") == 4]
    # One downloading event per track, each carrying a numeric progress.
    assert len(track_events) == 4
    assert all(p["status"] == "downloading" for p in track_events)
    assert [p["track_index"] for p in track_events] == [1, 2, 3, 4]
    pcts = [p["progress"] for p in track_events]
    assert all(isinstance(x, int) for x in pcts)
    # Monotonically increasing within the 10-80 band.
    assert pcts == sorted(pcts)
    assert 10 <= pcts[0] and pcts[-1] <= 80

    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_initial_downloading_progress_no_50_jump_for_streaming_provider(client):
    """For a provider that streams per-track progress, the initial 'downloading'
    event carries an explicit floor progress (10) so the bar does not bucket to
    50% and then snap back down to the first real per-track percent."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class StreamingProvider(SourceProvider):
        id = "test"
        name = "Test Provider"
        streams_progress = True

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            on_progress(DownloadProgress(completed=1, total=10, downloaded=1))
            return True

    clear_registry()
    register(StreamingProvider())
    test_client = make_test_app().test_client()

    payload = {
        "items": [
            {
                "artist": "Artist",
                "title": "Album",
                "album_id": 7,
                "source": "test",
                "match_url": "https://test.com",
            }
        ]
    }
    events = _collect_stream_events(test_client, payload)
    downloading = [
        e["progress"]
        for e in events
        if "progress" in e and e["progress"]["status"] == "downloading"
    ]
    # The first downloading event is the initial one (no track_total yet) and
    # carries the floor progress, never the 50 bucket.
    initial = downloading[0]
    assert "track_total" not in initial
    assert initial["progress"] == 10
    # Every downloading progress stays monotonic (no drop below the floor).
    pcts = [d["progress"] for d in downloading]
    assert pcts == sorted(pcts)
    assert min(pcts) >= 10

    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_initial_downloading_no_numeric_progress_for_nonstreaming_provider(client):
    """A provider that does NOT stream progress keeps the bare 'downloading' event
    (no numeric progress), so the frontend's per-status bucket still applies."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class OpaqueProvider(SourceProvider):
        id = "test"
        name = "Test Provider"
        # streams_progress defaults to False

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            return True

    clear_registry()
    register(OpaqueProvider())
    test_client = make_test_app().test_client()

    payload = {
        "items": [
            {
                "artist": "Artist",
                "title": "Album",
                "album_id": 8,
                "source": "test",
                "match_url": "https://test.com",
            }
        ]
    }
    events = _collect_stream_events(test_client, payload)
    downloading = [
        e["progress"]
        for e in events
        if "progress" in e and e["progress"]["status"] == "downloading"
    ]
    assert len(downloading) == 1
    assert "progress" not in downloading[0]

    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_partial_album_marked_downloaded_not_failed(client):
    """A partial album (some tracks errored, ≥1 succeeded) is reported as
    downloaded+partial, never failed (import what's available)."""
    from albfetcharr.web.routes import _stream_claim_lock, _stream_claim_state

    class PartialProvider(SourceProvider):
        id = "test"
        name = "Test Provider"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            # 5 tracks, 1 errored — still usable -> True.
            on_progress(
                DownloadProgress(completed=5, total=5, downloaded=4, errors=1, message="done")
            )
            return True

    clear_registry()
    register(PartialProvider())
    test_client = make_test_app().test_client()

    payload = {
        "items": [
            {
                "artist": "Artist",
                "title": "Album",
                "album_id": 9,
                "source": "test",
                "match_url": "https://test.com",
            }
        ]
    }
    # Import disabled so the terminal state is the downloaded/partial event.
    with patch("albfetcharr.web.routes.resolve_app_config") as mock_resolve:
        mock_app_cfg = MagicMock()
        mock_app_cfg.lidarr.base_url = "http://lidarr.test"
        mock_app_cfg.lidarr.api_key = "test_key"
        mock_app_cfg.lidarr.import_path = ""
        mock_app_cfg.yandex_options.clear_comments = False
        mock_resolve.return_value = mock_app_cfg
        events = _collect_stream_events(test_client, payload)

    progress_events = [e["progress"] for e in events if "progress" in e]
    statuses = [p["status"] for p in progress_events]
    assert "failed" not in statuses
    downloaded_events = [p for p in progress_events if p["status"] == "downloaded"]
    assert len(downloaded_events) == 1
    assert downloaded_events[0]["partial"] is True
    assert downloaded_events[0]["errors"] == 1
    # The album still completes (import disabled -> done).
    assert "done" in statuses

    with _stream_claim_lock:
        _stream_claim_state["claimed"] = False
        _stream_claim_state["claimed_at"] = None
        _stream_claim_state["last_seen"] = None


@pytest.mark.usefixtures("_clean_registry")
def test_index_returns_helpful_error_when_dist_missing(client):
    """Test that / returns helpful error when frontend not built."""
    with patch("importlib.resources.files") as mock_files:
        mock_files.side_effect = FileNotFoundError("static/dist/index.html not found")
        response = client.get("/")
        assert response.status_code == 500
        assert response.content_type == "text/plain"
        msg = response.get_data(as_text=True)
        assert "Frontend not built" in msg
        assert "npm run build" in msg


@pytest.mark.usefixtures("_clean_registry")
def test_api_config_uses_resolve_app_config(client):
    """Test /api/config reads all four fields from resolve_app_config, not load_* helpers."""
    with patch("albfetcharr.web.routes.resolve_app_config") as mock_resolve:
        mock_cfg = MagicMock()
        mock_cfg.yandex_options.quality = "1"
        mock_cfg.ui_defaults.language = "ru"
        mock_cfg.ui_defaults.theme = "dark"
        mock_cfg.lidarr.import_path = "/import"
        mock_resolve.return_value = mock_cfg

        response = client.get("/api/config")

    assert response.status_code == 200
    data = response.get_json()
    assert data["default_quality"] == 1
    assert data["default_lang"] == "ru"
    assert data["default_theme"] == "dark"
    assert data["import_enabled"] is True


@pytest.mark.usefixtures("_clean_registry")
@responses.activate
def test_api_wanted_uses_resolved_lidarr_config(client):
    """Test /api/wanted resolves lidarr config via resolve_app_config."""
    responses.add(
        responses.GET,
        "http://lidarr.resolved/api/v1/wanted/missing",
        json={"records": [], "totalRecords": 0},
        status=200,
    )
    responses.add(
        responses.GET,
        "http://lidarr.resolved/api/v1/rootfolder",
        json=[],
        status=200,
    )
    responses.add(
        responses.GET,
        "http://lidarr.resolved/api/v1/artist",
        json=[],
        status=200,
    )

    with patch("albfetcharr.web.routes.resolve_app_config") as mock_resolve:
        mock_cfg = MagicMock()
        mock_cfg.lidarr.base_url = "http://lidarr.resolved"
        mock_cfg.lidarr.api_key = "resolved_key"
        mock_resolve.return_value = mock_cfg

        with patch.dict("os.environ", {"DOWNLOAD_DIR": "/downloads"}):
            response = client.get("/api/wanted")

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


# ── Task 11: Session overrides behavioral tests ───────────────────────────────


def _wait_for_lock(timeout=5.0):
    """Acquire and release download_lock to wait for the background thread."""
    from albfetcharr.web.routes import download_lock

    acquired = download_lock.acquire(timeout=timeout)
    if acquired:
        download_lock.release()


@pytest.mark.usefixtures("_clean_registry")
def test_overrides_clear_comments_enabled_via_override():
    """yandex_clear_comments=1 in overrides triggers comment stripping even when env is 0."""

    class SuccessYandex(SourceProvider):
        id = "yandex"
        name = "Yandex Music"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            if log:
                log("ok")
            return True

    clear_registry()
    register(SuccessYandex())
    test_client = make_test_app().test_client()
    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "source": "yandex",
                "artist": "A",
                "title": "B",
                "match_url": "http://x",
                "album_id": 1,
            }
        ],
        "overrides": {"yandex_clear_comments": "1"},
    }

    # Force per-run dict empty so the global registry SuccessYandex is used.
    # (Prevents a container-level YANDEX_MUSIC_TOKEN from causing per-run to
    # construct a real YandexMusicProvider that would bypass the test fake.)
    with patch("albfetcharr.web.routes._build_per_run_providers", return_value={}):
        with patch.dict("os.environ", {"DOWNLOAD_DIR": "/fake", "ALBFETCHARR_CLEAR_COMMENTS": "0"}):
            with patch("albfetcharr.web.routes.clear_comments") as mock_cc:
                with patch("albfetcharr.web.routes.find_album_dir", return_value="/fake/A/B"):
                    test_client.post(
                        "/api/download",
                        data=json.dumps(payload),
                        content_type="application/json",
                    )
                    test_client.get("/api/download/stream").get_data(as_text=True)

    mock_cc.assert_called_once()


@pytest.mark.usefixtures("_clean_registry")
def test_overrides_clear_comments_disabled_via_override():
    """yandex_clear_comments=0 in overrides suppresses stripping even when env is 1."""

    class SuccessYandex(SourceProvider):
        id = "yandex"
        name = "Yandex Music"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            if log:
                log("ok")
            return True

    clear_registry()
    register(SuccessYandex())
    test_client = make_test_app().test_client()
    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "source": "yandex",
                "artist": "A",
                "title": "B",
                "match_url": "http://x",
                "album_id": 1,
            }
        ],
        "overrides": {"yandex_clear_comments": "0"},
    }

    with patch("albfetcharr.web.routes._build_per_run_providers", return_value={}):
        with patch.dict("os.environ", {"DOWNLOAD_DIR": "/fake", "ALBFETCHARR_CLEAR_COMMENTS": "1"}):
            with patch("albfetcharr.web.routes.clear_comments") as mock_cc:
                with patch("albfetcharr.web.routes.find_album_dir", return_value="/fake/A/B"):
                    test_client.post(
                        "/api/download",
                        data=json.dumps(payload),
                        content_type="application/json",
                    )
                    test_client.get("/api/download/stream").get_data(as_text=True)

    mock_cc.assert_not_called()


@pytest.mark.usefixtures("_clean_registry")
def test_overrides_quality_override_beats_default():
    """yandex_quality override changes the quality arg passed to the provider."""
    received = {}

    class QualityProvider(SourceProvider):
        id = "yandex"
        name = "Yandex Music"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            received["quality"] = quality
            if log:
                log("ok")
            return True

    clear_registry()
    register(QualityProvider())
    test_client = make_test_app().test_client()
    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "source": "yandex",
                "artist": "A",
                "title": "B",
                "match_url": "http://x",
                "album_id": 1,
            }
        ],
        "overrides": {"yandex_quality": "0"},
    }

    # Force per-run dict empty so the global registry QualityProvider is used.
    with patch("albfetcharr.web.routes._build_per_run_providers", return_value={}):
        with patch.dict("os.environ", {"DOWNLOAD_DIR": "/fake"}):
            test_client.post(
                "/api/download",
                data=json.dumps(payload),
                content_type="application/json",
            )
            test_client.get("/api/download/stream").get_data(as_text=True)

    assert received.get("quality") == "0", f"expected '0', got {received.get('quality')!r}"


@pytest.mark.usefixtures("_clean_registry")
def test_overrides_quality_per_item_beats_override():
    """Per-item quality wins over the session override yandex_quality."""
    received = {}

    class QualityProvider(SourceProvider):
        id = "yandex"
        name = "Yandex Music"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            received["quality"] = quality
            if log:
                log("ok")
            return True

    clear_registry()
    register(QualityProvider())
    test_client = make_test_app().test_client()
    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "source": "yandex",
                "artist": "A",
                "title": "B",
                "match_url": "http://x",
                "album_id": 1,
                "quality": 1,  # per-item quality "1"
            }
        ],
        "overrides": {"yandex_quality": "0"},  # override says "0"
    }

    # Force per-run dict empty so the global registry QualityProvider is used.
    with patch("albfetcharr.web.routes._build_per_run_providers", return_value={}):
        with patch.dict("os.environ", {"DOWNLOAD_DIR": "/fake"}):
            test_client.post(
                "/api/download",
                data=json.dumps(payload),
                content_type="application/json",
            )
            test_client.get("/api/download/stream").get_data(as_text=True)

    # Per-item quality "1" must win over the "0" override.
    assert received.get("quality") == "1", f"expected '1', got {received.get('quality')!r}"


@pytest.mark.usefixtures("_clean_registry")
def test_overrides_ytdlp_format_bakes_into_per_run_provider():
    """ytdlp_format override is baked into the per-run YouTubeMusicProvider._opts."""
    captured_opts = {}

    class CapturingYtProvider:
        """Stands in for YouTubeMusicProvider; captures constructor opts."""

        def __init__(self, opts):
            captured_opts["opts"] = opts

        def download(self, match, *, quality=None, log=None, on_progress=None):
            if log:
                log("ok")
            return True

        @property
        def name(self):
            return "YouTube Music"

        streams_progress = False

    class FakeYtRegistry(SourceProvider):
        """Registered in global registry so pre-flight get_provider check passes."""

        id = "youtube_music"
        name = "YouTube Music"

        def search(self, artist, album, limit=5):
            return []

        def download(self, match, *, quality=None, log=None, on_progress=None):
            return True

    clear_registry()
    register(FakeYtRegistry())
    test_client = make_test_app().test_client()
    test_client.post("/api/download/stream/claim")

    payload = {
        "items": [
            {
                "source": "youtube_music",
                "artist": "A",
                "title": "B",
                "match_url": "http://x",
                "album_id": 1,
            }
        ],
        "overrides": {"ytdlp_format": "mp3"},
    }

    # Patch YouTubeMusicProvider so the per-run construction uses CapturingYtProvider.
    with patch("albfetcharr.sources.youtube_music.YouTubeMusicProvider", CapturingYtProvider):
        with patch.dict("os.environ", {"DOWNLOAD_DIR": "/fake"}):
            test_client.post(
                "/api/download",
                data=json.dumps(payload),
                content_type="application/json",
            )
            test_client.get("/api/download/stream").get_data(as_text=True)

    opts = captured_opts.get("opts")
    assert opts is not None, (
        "YouTubeMusicProvider was not constructed (per-run construction missing)"
    )
    assert opts.audio_format == "mp3", f"expected 'mp3', got {opts.audio_format!r}"
