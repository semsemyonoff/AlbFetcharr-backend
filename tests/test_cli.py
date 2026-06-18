"""Tests for the AlbFetcharr CLI."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from albfetcharr.cli import cmd_download, cmd_wanted, detect_source, main
from albfetcharr.sources.base import DownloadProgress


def test_wanted_help():
    """Test that 'wanted' subcommand shows help."""
    with patch("sys.argv", ["albfetcharr", "wanted", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


def test_download_help():
    """Test that 'download' subcommand shows help."""
    with patch("sys.argv", ["albfetcharr", "download", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


@patch("albfetcharr.cli.get_provider")
@patch("albfetcharr.cli.get_wanted_albums")
@patch("albfetcharr.cli.validate_library_map")
@patch("albfetcharr.cli.get_root_folders", return_value=[])
@patch("albfetcharr.cli.resolve_app_config")
def test_wanted_no_albums(
    mock_resolve_config,
    mock_get_root_folders,
    mock_validate,
    mock_get_albums,
    mock_get_provider,
    capsys,
):
    """Test 'wanted' subcommand when no albums found."""
    mock_config = MagicMock()
    mock_config.lidarr.base_url = "http://lidarr"
    mock_config.lidarr.api_key = "key"
    mock_config.yandex_options.download_dir = "/downloads"
    mock_resolve_config.return_value = mock_config

    mock_get_albums.return_value = []

    args = argparse.Namespace(no_import=False, source=None)
    cmd_wanted(args)

    captured = capsys.readouterr()
    assert "No wanted albums found" in captured.out


@patch("albfetcharr.cli.check_album_status")
@patch("albfetcharr.cli.get_provider")
@patch("albfetcharr.cli.get_wanted_albums")
@patch("albfetcharr.cli.validate_library_map")
@patch("albfetcharr.cli.get_root_folders", return_value=[])
@patch("albfetcharr.cli.resolve_app_config")
def test_wanted_with_albums(
    mock_resolve_config,
    mock_get_root_folders,
    mock_validate,
    mock_get_albums,
    mock_get_provider,
    mock_check_status,
    capsys,
):
    """Test 'wanted' subcommand with albums found."""
    mock_config = MagicMock()
    mock_config.lidarr.base_url = "http://lidarr"
    mock_config.lidarr.api_key = "key"
    mock_config.lidarr.import_path = ""
    mock_config.yandex_options.download_dir = "/downloads"
    mock_resolve_config.return_value = mock_config

    mock_albums = [
        {
            "id": 1,
            "title": "Test Album",
            "artist": {"artistName": "Test Artist"},
            "releaseDate": "2024-01-01",
            "statistics": {"trackFileCount": 0},
        }
    ]
    mock_get_albums.return_value = mock_albums

    mock_provider = MagicMock()
    mock_provider.search.return_value = []
    mock_get_provider.return_value = mock_provider

    mock_check_status.return_value = "missing"

    args = argparse.Namespace(no_import=False, source=None)
    cmd_wanted(args)

    captured = capsys.readouterr()
    assert "Wanted albums (1):" in captured.out
    assert "Test Artist" in captured.out
    assert "Test Album" in captured.out


@patch("albfetcharr.cli.clear_comments")
@patch("albfetcharr.cli.find_album_dir")
@patch("albfetcharr.cli.check_album_status")
@patch("albfetcharr.cli.get_provider")
@patch("albfetcharr.cli.get_wanted_albums")
@patch("albfetcharr.cli.validate_library_map")
@patch("albfetcharr.cli.get_root_folders", return_value=[])
@patch("albfetcharr.cli.resolve_app_config")
def test_wanted_clear_comments_from_resolved_config(
    mock_resolve_config,
    mock_get_root_folders,
    mock_validate,
    mock_get_albums,
    mock_get_provider,
    mock_check_status,
    mock_find_album_dir,
    mock_clear_comments,
    capsys,
):
    """CLI download path reads clear_comments from resolved config."""
    mock_config = MagicMock()
    mock_config.lidarr.base_url = "http://lidarr"
    mock_config.lidarr.api_key = "key"
    mock_config.lidarr.import_path = ""
    mock_config.yandex_options.clear_comments = True
    mock_resolve_config.return_value = mock_config

    mock_albums = [
        {
            "id": 1,
            "title": "Clear Album",
            "artist": {"artistName": "Clear Artist"},
            "releaseDate": "2024-01-01",
        }
    ]
    mock_get_albums.return_value = mock_albums

    mock_provider = MagicMock()
    mock_provider.name = "yandex"

    def _download(match, *, on_progress=None, **kwargs):
        return True

    mock_provider.download.side_effect = _download
    mock_provider.search.return_value = [MagicMock(url="https://music.yandex.ru/album/1")]
    mock_get_provider.return_value = mock_provider

    mock_check_status.return_value = "missing"
    mock_find_album_dir.return_value = "/downloads/Clear Artist/Clear Album"

    args = argparse.Namespace(no_import=False, source="yandex")
    cmd_wanted(args)

    mock_clear_comments.assert_called_once_with("/downloads/Clear Artist/Clear Album")


@patch("albfetcharr.cli.clear_comments")
@patch("albfetcharr.cli.find_album_dir")
@patch("albfetcharr.cli.check_album_status")
@patch("albfetcharr.cli.get_provider")
@patch("albfetcharr.cli.get_wanted_albums")
@patch("albfetcharr.cli.validate_library_map")
@patch("albfetcharr.cli.get_root_folders", return_value=[])
@patch("albfetcharr.cli.resolve_app_config")
def test_wanted_clear_comments_false_skips(
    mock_resolve_config,
    mock_get_root_folders,
    mock_validate,
    mock_get_albums,
    mock_get_provider,
    mock_check_status,
    mock_find_album_dir,
    mock_clear_comments,
    capsys,
):
    """CLI download path skips clear_comments when resolved config has it false."""
    mock_config = MagicMock()
    mock_config.lidarr.base_url = "http://lidarr"
    mock_config.lidarr.api_key = "key"
    mock_config.lidarr.import_path = ""
    mock_config.yandex_options.clear_comments = False
    mock_resolve_config.return_value = mock_config

    mock_albums = [
        {
            "id": 1,
            "title": "No Clear Album",
            "artist": {"artistName": "No Clear Artist"},
            "releaseDate": "2024-01-01",
        }
    ]
    mock_get_albums.return_value = mock_albums

    mock_provider = MagicMock()
    mock_provider.name = "yandex"

    def _download(match, *, on_progress=None, **kwargs):
        return True

    mock_provider.download.side_effect = _download
    mock_provider.search.return_value = [MagicMock(url="https://music.yandex.ru/album/2")]
    mock_get_provider.return_value = mock_provider

    mock_check_status.return_value = "missing"

    args = argparse.Namespace(no_import=False, source="yandex")
    cmd_wanted(args)

    mock_clear_comments.assert_not_called()


@patch("albfetcharr.cli.get_provider")
def test_download_with_explicit_source(mock_get_provider):
    """Test 'download' subcommand with explicit source."""
    mock_provider = MagicMock()
    mock_provider.download.return_value = True
    mock_get_provider.return_value = mock_provider

    url = "https://some-source.com/album/12345"
    args = argparse.Namespace(url=url, source="yandex")

    with patch("builtins.print"):
        cmd_download(args)

    mock_get_provider.assert_called_with("yandex")


@patch("albfetcharr.cli.get_provider")
def test_download_success_reports_clean(mock_get_provider, capsys):
    """A non-partial success (no on_progress errors) prints the plain success line."""
    mock_provider = MagicMock()
    mock_provider.download.return_value = True
    mock_get_provider.return_value = mock_provider

    args = argparse.Namespace(url="https://music.yandex.ru/album/1", source=None)
    cmd_download(args)

    out = capsys.readouterr().out
    assert "Download completed successfully." in out
    assert "partial" not in out.lower()


@patch("albfetcharr.cli.get_provider")
def test_download_partial_reports_partial(mock_get_provider, capsys):
    """A partial album (download returns True but some tracks errored) is reported
    as partial, not an unqualified success."""
    mock_provider = MagicMock()

    def _dl(match, *, on_progress=None, **kwargs):
        if on_progress:
            on_progress(DownloadProgress(completed=10, total=10, downloaded=7, errors=3))
        return True

    mock_provider.download.side_effect = _dl
    mock_get_provider.return_value = mock_provider

    args = argparse.Namespace(url="https://music.youtube.com/browse/X", source="youtube_music")
    cmd_download(args)

    out = capsys.readouterr().out
    assert "partially" in out.lower()
    assert "3 track(s) failed" in out
    assert "7/10 available" in out


@patch("albfetcharr.cli.get_provider")
def test_download_failure(mock_get_provider):
    """Test 'download' subcommand when download fails."""
    mock_provider = MagicMock()
    mock_provider.download.return_value = False
    mock_get_provider.return_value = mock_provider

    url = "https://music.yandex.ru/album/12345"
    args = argparse.Namespace(url=url, source=None)

    with patch("builtins.print"):
        with pytest.raises(SystemExit) as exc:
            cmd_download(args)
        assert exc.value.code == 1


@patch("albfetcharr.cli.bootstrap_default_providers")
@patch("albfetcharr.cli.cmd_wanted")
def test_main_wanted(mock_cmd_wanted, mock_bootstrap):
    """Test main() with 'wanted' subcommand."""
    with patch("sys.argv", ["albfetcharr", "wanted"]):
        main()

    mock_bootstrap.assert_called_once()
    mock_cmd_wanted.assert_called_once()


@patch("albfetcharr.cli.bootstrap_default_providers")
@patch("albfetcharr.cli.cmd_download")
def test_main_download(mock_cmd_download, mock_bootstrap):
    """Test main() with 'download' subcommand."""
    with patch(
        "sys.argv",
        ["albfetcharr", "download", "https://music.yandex.ru/album/12345"],
    ):
        main()

    mock_bootstrap.assert_called_once()
    mock_cmd_download.assert_called_once()


def test_main_no_args(capsys):
    """Test main() with no arguments shows help."""
    with patch("sys.argv", ["albfetcharr"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    captured = capsys.readouterr()
    assert "usage:" in captured.out or "AlbFetcharr" in captured.out


@pytest.mark.parametrize(
    "url,expected_source",
    [
        # Yandex Music
        ("https://music.yandex.ru/album/12345", "yandex"),
        ("https://music.yandex.kz/album/12345", "yandex"),
        ("music.yandex.ru/album/12345", "yandex"),
        # YouTube Music
        ("https://music.youtube.com/browse/MPREb_test", "youtube_music"),
        ("https://www.youtube.com/playlist?list=test", "youtube_music"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube_music"),
        ("https://youtube.com/watch?v=test", "youtube_music"),
        # SoundCloud
        ("https://soundcloud.com/user/album-name", "soundcloud"),
        ("https://www.soundcloud.com/user/track-name", "soundcloud"),
        # Unsupported
        ("https://spotify.com/album/12345", None),
        ("https://apple.music/album/12345", None),
        ("https://example.com/album", None),
    ],
)
def test_detect_source(url, expected_source):
    """Test URL-based source auto-detection."""
    assert detect_source(url) == expected_source
