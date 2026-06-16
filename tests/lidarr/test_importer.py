"""Tests for albfetcharr.lidarr.importer module."""

from unittest.mock import patch

import responses

from albfetcharr.lidarr.importer import post_import_cleanup, run_import


@responses.activate
def test_run_import_happy_path():
    """Test successful import: files scanned, command triggered, completed."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    download_path = "/downloads"

    manualimport_response = [
        {
            "path": "/downloads/artist1/album1",
            "artist": {"id": 1, "name": "Artist 1"},
            "album": {
                "id": 101,
                "releases": [{"id": 1001, "monitored": True}],
            },
            "tracks": [{"id": 1}, {"id": 2}],
            "rejections": [],
            "quality": {"quality": {"id": 1}},
        },
        {
            "path": "/downloads/artist2/album2",
            "artist": {"id": 2, "name": "Artist 2"},
            "album": {
                "id": 102,
                "releases": [{"id": 1002, "monitored": True}],
            },
            "tracks": [{"id": 3}, {"id": 4}],
            "rejections": [],
            "quality": {"quality": {"id": 1}},
        },
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/manualimport",
        json=manualimport_response,
        status=200,
    )

    responses.add(
        responses.POST,
        f"{base_url}/api/v1/command",
        json={"id": 999},
        status=201,
    )

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/command/999",
        json={"status": "completed"},
        status=200,
    )

    log_messages = []
    result = run_import(base_url, api_key, download_path, log=log_messages.append)

    assert result is True
    assert any("Importing 2 file(s)" in msg for msg in log_messages)
    assert any("completed" in msg for msg in log_messages)


@responses.activate
def test_run_import_with_rejections():
    """Test import skips files with rejections."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    download_path = "/downloads"

    manualimport_response = [
        {
            "path": "/downloads/artist1/album1",
            "artist": {"id": 1, "name": "Artist 1"},
            "album": {"id": 101},
            "tracks": [{"id": 1}],
            "rejections": [{"reason": "Invalid format"}],
            "quality": {"quality": {"id": 1}},
        },
        {
            "path": "/downloads/artist2/album2",
            "artist": {"id": 2, "name": "Artist 2"},
            "album": {
                "id": 102,
                "releases": [{"id": 1002, "monitored": True}],
            },
            "tracks": [{"id": 3}],
            "rejections": [],
            "quality": {"quality": {"id": 1}},
        },
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/manualimport",
        json=manualimport_response,
        status=200,
    )

    responses.add(
        responses.POST,
        f"{base_url}/api/v1/command",
        json={"id": 999},
        status=201,
    )

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/command/999",
        json={"status": "completed"},
        status=200,
    )

    log_messages = []
    result = run_import(base_url, api_key, download_path, log=log_messages.append)

    assert result is True
    assert any("Skipping" in msg and "Invalid format" in msg for msg in log_messages)
    assert any("Importing 1 file(s)" in msg for msg in log_messages)


@responses.activate
def test_run_import_choose_album_release():
    """Test that run_import chooses the monitored album release."""
    import json

    base_url = "http://lidarr:8686"
    api_key = "test_key"
    download_path = "/downloads"

    manualimport_response = [
        {
            "path": "/downloads/artist1/album1",
            "artist": {"id": 1, "name": "Artist 1"},
            "album": {
                "id": 101,
                "releases": [
                    {"id": 1001, "monitored": False},
                    {"id": 1002, "monitored": True},
                    {"id": 1003, "monitored": False},
                ],
            },
            "tracks": [{"id": 1}],
            "rejections": [],
            "quality": {"quality": {"id": 1}},
        },
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/manualimport",
        json=manualimport_response,
        status=200,
    )

    def verify_post(request):
        body = json.loads(request.body)
        files = body.get("files", [])
        assert len(files) == 1
        assert files[0]["albumReleaseId"] == 1002
        return (201, {}, json.dumps({"id": 999}))

    responses.add_callback(
        responses.POST,
        f"{base_url}/api/v1/command",
        callback=verify_post,
        content_type="application/json",
    )

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/command/999",
        json={"status": "completed"},
        status=200,
    )

    log_messages = []
    result = run_import(base_url, api_key, download_path, log=log_messages.append)

    assert result is True


@responses.activate
def test_run_import_empty_folder():
    """Test import when no files are found."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    download_path = "/downloads"

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/manualimport",
        json=[],
        status=200,
    )

    log_messages = []
    result = run_import(base_url, api_key, download_path, log=log_messages.append)

    assert result is False
    assert any("No importable files" in msg for msg in log_messages)


@responses.activate
def test_run_import_no_matching_files():
    """Test import when Lidarr finds files but none match an artist/album."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    download_path = "/downloads"

    manualimport_response = [
        {
            "path": "/downloads/unknown",
            "artist": None,
            "album": None,
            "tracks": [],
        },
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/manualimport",
        json=manualimport_response,
        status=200,
    )

    log_messages = []
    result = run_import(base_url, api_key, download_path, log=log_messages.append)

    assert result is False
    assert any("matched an artist/album" in msg for msg in log_messages)


@responses.activate
def test_run_import_failed_status():
    """Test import when command fails."""
    base_url = "http://lidarr:8686"
    api_key = "test_key"
    download_path = "/downloads"

    manualimport_response = [
        {
            "path": "/downloads/artist1/album1",
            "artist": {"id": 1, "name": "Artist 1"},
            "album": {
                "id": 101,
                "releases": [{"id": 1001, "monitored": True}],
            },
            "tracks": [{"id": 1}],
            "rejections": [],
            "quality": {"quality": {"id": 1}},
        },
    ]

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/manualimport",
        json=manualimport_response,
        status=200,
    )

    responses.add(
        responses.POST,
        f"{base_url}/api/v1/command",
        json={"id": 999},
        status=201,
    )

    responses.add(
        responses.GET,
        f"{base_url}/api/v1/command/999",
        json={"status": "failed"},
        status=200,
    )

    log_messages = []
    result = run_import(base_url, api_key, download_path, log=log_messages.append)

    assert result is False
    assert any("did not complete" in msg for msg in log_messages)


def test_post_import_cleanup(tmp_path):
    """Test post_import_cleanup moves cover and removes directories."""
    download_dir = tmp_path / "downloads"
    library_dir = tmp_path / "library"

    artist_dir = download_dir / "Artist One"
    album_dir = artist_dir / "Album One"
    album_dir.mkdir(parents=True)

    cover_src = album_dir / "cover.jpg"
    cover_src.write_text("fake cover")

    (album_dir / "track1.mp3").write_text("fake audio")

    lib_album_dir = library_dir / "Artist One" / "Album One"
    lib_album_dir.mkdir(parents=True)

    base_url = "http://lidarr:8686"
    api_key = "test_key"

    albums = [
        {
            "artist": "Artist One",
            "title": "Album One",
            "album_id": 101,
        }
    ]

    log_messages = []

    with patch(
        "albfetcharr.lidarr.importer.get_album_path"
    ) as mock_get_path, patch(
        "albfetcharr.lidarr.importer.resolve_library_path"
    ) as mock_resolve:
        mock_get_path.return_value = str(lib_album_dir)
        mock_resolve.side_effect = lambda x: x

        post_import_cleanup(
            str(download_dir),
            base_url,
            api_key,
            albums,
            log=log_messages.append,
        )

    assert not album_dir.exists(), "Album directory should be removed"
    assert not artist_dir.exists(), "Empty artist directory should be removed"
    assert (lib_album_dir / "cover.jpg").exists(), "Cover should be moved to library"
    assert any("Moving cover" in msg for msg in log_messages)
    assert any("Removed download dir" in msg for msg in log_messages)


def test_post_import_cleanup_no_cover(tmp_path):
    """Test post_import_cleanup when there is no cover.jpg."""
    download_dir = tmp_path / "downloads"

    artist_dir = download_dir / "Artist Two"
    album_dir = artist_dir / "Album Two"
    album_dir.mkdir(parents=True)
    (album_dir / "track1.mp3").write_text("fake audio")

    base_url = "http://lidarr:8686"
    api_key = "test_key"

    albums = [
        {
            "artist": "Artist Two",
            "title": "Album Two",
            "album_id": 102,
        }
    ]

    log_messages = []

    with patch(
        "albfetcharr.lidarr.importer.get_album_path"
    ) as mock_get_path, patch(
        "albfetcharr.lidarr.importer.resolve_library_path"
    ) as mock_resolve:
        mock_get_path.return_value = "/library/Artist Two/Album Two"
        mock_resolve.side_effect = lambda x: x

        post_import_cleanup(
            str(download_dir),
            base_url,
            api_key,
            albums,
            log=log_messages.append,
        )

    assert not album_dir.exists(), "Album directory should be removed"
    assert any("Removed download dir" in msg for msg in log_messages)


def test_post_import_cleanup_album_not_found(tmp_path):
    """Test post_import_cleanup when album directory is not found."""
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    base_url = "http://lidarr:8686"
    api_key = "test_key"

    albums = [
        {
            "artist": "Nonexistent Artist",
            "title": "Nonexistent Album",
            "album_id": 999,
        }
    ]

    log_messages = []

    with patch(
        "albfetcharr.lidarr.importer.get_album_path"
    ) as mock_get_path:
        post_import_cleanup(
            str(download_dir),
            base_url,
            api_key,
            albums,
            log=log_messages.append,
        )

    assert mock_get_path.call_count == 0, "Should not call get_album_path if album dir not found"


def test_post_import_cleanup_library_path_inaccessible(tmp_path):
    """Test post_import_cleanup when library path doesn't exist."""
    download_dir = tmp_path / "downloads"

    artist_dir = download_dir / "Artist Three"
    album_dir = artist_dir / "Album Three"
    album_dir.mkdir(parents=True)

    cover_src = album_dir / "cover.jpg"
    cover_src.write_text("fake cover")
    (album_dir / "track1.mp3").write_text("fake audio")

    base_url = "http://lidarr:8686"
    api_key = "test_key"

    albums = [
        {
            "artist": "Artist Three",
            "title": "Album Three",
            "album_id": 103,
        }
    ]

    log_messages = []

    with patch(
        "albfetcharr.lidarr.importer.get_album_path"
    ) as mock_get_path, patch(
        "albfetcharr.lidarr.importer.resolve_library_path"
    ) as mock_resolve:
        mock_get_path.return_value = "/nonexistent/library/path"
        mock_resolve.side_effect = lambda x: x

        post_import_cleanup(
            str(download_dir),
            base_url,
            api_key,
            albums,
            log=log_messages.append,
        )

    assert not album_dir.exists(), "Album directory should still be removed"
    assert any("WARNING: Library path not accessible" in msg for msg in log_messages)
    assert any("Removed download dir" in msg for msg in log_messages)
