"""Tests for albfetcharr.lidarr.client module."""

import responses

from albfetcharr.lidarr.client import (
    get_all_artists,
    get_artist_root_folder,
    get_lidarr_track_count,
    get_root_folders,
    get_wanted_albums,
)


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
