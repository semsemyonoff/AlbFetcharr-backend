"""Tests for albfetcharr.lidarr.client module."""

import logging

import pytest
import responses

from albfetcharr.lidarr.client import (
    get_all_artists,
    get_artist_root_folder,
    get_lidarr_track_count,
    get_root_folders,
    get_wanted_albums,
)


@pytest.fixture()
def capture_albfetcharr_logs(caplog):
    """Capture albfetcharr.* log records directly on the parent logger.

    Attaching caplog's handler to the ``albfetcharr`` logger (rather than relying
    on propagation to root) makes capture robust even after create_app() has set
    ``propagate = False`` on it in an earlier test.
    """
    logger = logging.getLogger("albfetcharr")
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(prev_level)


@responses.activate
def test_request_logs_request_and_response_at_debug(capture_albfetcharr_logs):
    """A successful Lidarr call logs the request and response at DEBUG."""
    base_url = "http://lidarr:8686"
    responses.add(
        responses.GET,
        f"{base_url}/api/v1/rootfolder",
        json=[{"id": 1, "path": "/music"}],
        status=200,
    )

    get_root_folders(base_url, "secret-key")

    text = capture_albfetcharr_logs.text
    assert "request: GET" in text
    assert "response: 200 GET" in text
    # The API key must never appear in the logs.
    assert "secret-key" not in text


@responses.activate
def test_request_logs_error_status_at_warning(capture_albfetcharr_logs):
    """A 4xx/5xx response is logged at WARNING so it's visible at default level."""
    base_url = "http://lidarr:8686"
    responses.add(
        responses.GET,
        f"{base_url}/api/v1/artist",
        json={"error": "boom"},
        status=500,
    )

    with pytest.raises(Exception):
        get_all_artists(base_url, "test_key")

    records = [r for r in capture_albfetcharr_logs.records if r.levelno == logging.WARNING]
    assert any("response: 500 GET" in r.getMessage() for r in records)


@responses.activate
def test_get_root_folders():
    """Test fetching root folders from Lidarr."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    expected_folders = [
        {"id": 1, "path": "/music"},
        {"id": 2, "path": "/downloads"},
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/rootfolder",
        json=expected_folders,
        status=200,
    )

    result = get_root_folders(base_url, api_key)
    assert result == expected_folders


@responses.activate
def test_get_all_artists():
    """Test fetching all artists from Lidarr."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    expected_artists = [
        {"id": 1, "artistName": "Artist One"},
        {"id": 2, "artistName": "Artist Two"},
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/artist",
        json=expected_artists,
        status=200,
    )

    result = get_all_artists(base_url, api_key)
    assert result == expected_artists


def test_get_artist_root_folder():
    """Test determining which root folder an artist belongs to."""
    root_folders = [
        {"path": "/music"},
        {"path": "/music/classical"},
        {"path": "/downloads"},
    ]

    # Exact match
    assert get_artist_root_folder("/music/classical/composer", root_folders) == "/music/classical"

    # Prefix match (longest)
    assert get_artist_root_folder("/music/rock/band", root_folders) == "/music"

    # No match
    assert get_artist_root_folder("/other/path", root_folders) == ""

    # Path with trailing slash
    assert get_artist_root_folder("/music/pop/", root_folders) == "/music"


@responses.activate
def test_get_wanted_albums_single_page():
    """Test fetching wanted albums on a single page."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    page_data = {
        "records": [
            {"id": 1, "title": "Album One"},
            {"id": 2, "title": "Album Two"},
        ],
        "totalRecords": 2,
    }

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/wanted/missing",
        json=page_data,
        status=200,
    )

    result = get_wanted_albums(base_url, api_key)
    assert len(result) == 2
    assert result[0]["title"] == "Album One"


@responses.activate
def test_get_wanted_albums_pagination():
    """Test fetching wanted albums across multiple pages."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"

    # First page
    responses.add(
        responses.GET,
        f"{base_url}/api/v1/wanted/missing",
        json={
            "records": [
                {"id": 1, "title": "Album One"},
                {"id": 2, "title": "Album Two"},
            ],
            "totalRecords": 3,
        },
        status=200,
    )

    # Second page
    responses.add(
        responses.GET,
        f"{base_url}/api/v1/wanted/missing",
        json={
            "records": [
                {"id": 3, "title": "Album Three"},
            ],
            "totalRecords": 3,
        },
        status=200,
    )

    result = get_wanted_albums(base_url, api_key)
    assert len(result) == 3
    assert result[0]["title"] == "Album One"
    assert result[2]["title"] == "Album Three"


@responses.activate
def test_get_lidarr_track_count():
    """Test fetching track count for an album."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    album_id = 42
    tracks = [
        {"id": 1, "title": "Track 1"},
        {"id": 2, "title": "Track 2"},
        {"id": 3, "title": "Track 3"},
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/track",
        json=tracks,
        status=200,
    )

    result = get_lidarr_track_count(base_url, api_key, album_id)
    assert result == 3
