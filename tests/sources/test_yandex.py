"""Tests for YandexMusicProvider."""

from unittest.mock import MagicMock

import pytest

from albfetcharr.config import YandexOptions
from albfetcharr.sources.base import Match
from albfetcharr.sources.yandex import YandexMusicProvider


def _match(url="https://music.yandex.ru/album/12345", artist="The Artist", title="The Album"):
    """Build a download Match (title/artists are the Lidarr-requested names)."""
    return Match(
        source="yandex",
        url=url,
        title=title,
        artists=artist,
        cover_url=None,
        year=None,
        track_count=None,
    )


@pytest.fixture
def yandex_options():
    """Create a default YandexOptions for testing."""
    return YandexOptions(
        quality="2",
        lyrics_format="lrc",
        cover_resolution="400",
        embed_cover=False,
        skip_existing=True,
        delay="0",
        compat_level="1",
        timeout="20",
        tries="20",
        retry_delay="5",
        stick_to_artist=False,
        only_music=False,
        unsafe_path=False,
        download_dir="/downloads",
    )


@pytest.fixture
def provider(yandex_options):
    """Create a YandexMusicProvider instance."""
    return YandexMusicProvider(token="test_token", options=yandex_options)


class TestBuildCmd:
    """Test command building."""

    def test_build_cmd_basic(self, provider):
        """Test basic command with defaults."""
        cmd = provider._build_cmd(_match())
        assert "yandex-music-downloader" in cmd
        assert "--token" in cmd
        assert "test_token" in cmd
        assert "--url" in cmd
        assert "https://music.yandex.ru/album/12345" in cmd
        assert "--quality" in cmd
        assert "--skip-existing" in cmd

    def test_build_cmd_quality_override(self, provider):
        """Test quality override."""
        cmd = provider._build_cmd(_match(), quality_override="1")
        idx = cmd.index("--quality")
        assert cmd[idx + 1] == "1"

    def test_build_cmd_pins_path_pattern_to_lidarr_names(self, provider):
        """--path-pattern bakes in the Lidarr artist/album as literal segments."""
        cmd = provider._build_cmd(_match(artist="The Artist", title="The Album"))
        idx = cmd.index("--path-pattern")
        assert cmd[idx + 1] == "The Artist/The Album/#number - #title"

    def test_build_cmd_sanitizes_path_pattern_segments(self, provider):
        """Filesystem-hostile chars in Lidarr names are stripped from the pattern."""
        cmd = provider._build_cmd(_match(artist="AC/DC", title="Back: In/Black"))
        idx = cmd.index("--path-pattern")
        assert cmd[idx + 1] == "ACDC/Back InBlack/#number - #title"

    def test_build_cmd_all_flags(self):
        """Test command with all optional flags enabled."""
        options = YandexOptions(
            quality="2",
            lyrics_format="txt",
            cover_resolution="500",
            embed_cover=True,
            skip_existing=True,
            delay="1",
            compat_level="2",
            timeout="30",
            tries="30",
            retry_delay="10",
            stick_to_artist=True,
            only_music=True,
            unsafe_path=True,
            download_dir="/music",
        )
        provider = YandexMusicProvider(token="test", options=options)
        cmd = provider._build_cmd(_match(url="https://music.yandex.ru/album/999"))

        assert "--embed-cover" in cmd
        assert "--stick-to-artist" in cmd
        assert "--only-music" in cmd
        assert "--unsafe-path" in cmd
        assert "/music" in cmd

    def test_build_cmd_no_skip_existing(self):
        """Test command when skip_existing is False."""
        options = YandexOptions(
            quality="2",
            lyrics_format="lrc",
            cover_resolution="400",
            embed_cover=False,
            skip_existing=False,
            delay="0",
            compat_level="1",
            timeout="20",
            tries="20",
            retry_delay="5",
            stick_to_artist=False,
            only_music=False,
            unsafe_path=False,
            download_dir="/downloads",
        )
        provider = YandexMusicProvider(token="test", options=options)
        cmd = provider._build_cmd(_match())
        assert "--skip-existing" not in cmd


class TestSearch:
    """Test search functionality."""

    def test_search_empty_results(self, provider, mocker):
        """Test search with no results."""
        mock_client = MagicMock()
        mock_client.search.return_value = None
        mocker.patch.object(provider, "_ensure_client", return_value=mock_client)

        results = provider.search("Unknown Artist", "Unknown Album")
        assert results == []

    def test_search_no_albums(self, provider, mocker):
        """Test search when results have no albums."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.albums = None
        mock_client.search.return_value = mock_result
        mocker.patch.object(provider, "_ensure_client", return_value=mock_client)

        results = provider.search("Artist", "Album")
        assert results == []

    def test_search_artist_match(self, provider, mocker):
        """Test search prefers artist match."""
        mock_client = MagicMock()

        # Create mock album with matching artist
        mock_album = MagicMock()
        mock_album.id = 12345
        mock_album.title = "Test Album"
        mock_album.release_date = None
        mock_album.track_count = 2

        artist_mock = MagicMock()
        artist_mock.name = "Test Artist"
        mock_album.artists = [artist_mock]

        mock_result = MagicMock()
        mock_result.albums.results = [mock_album]
        mock_client.search.return_value = mock_result

        mocker.patch.object(provider, "_ensure_client", return_value=mock_client)

        results = provider.search("Test Artist", "Test Album")
        assert len(results) == 1
        assert results[0].source == "yandex"
        assert results[0].url == "https://music.yandex.ru/album/12345"
        assert results[0].title == "Test Album"
        assert results[0].artists == "Test Artist"
        assert results[0].track_count == 2

    def test_search_multiple_results(self, provider, mocker):
        """Test search returns multiple results."""
        mock_client = MagicMock()

        albums = []
        for i in range(3):
            album = MagicMock()
            album.id = 10000 + i
            album.title = f"Album {i}"
            album.release_date = None
            album.track_count = 0
            artist = MagicMock()
            artist.name = f"Artist {i}"
            album.artists = [artist]
            albums.append(album)

        mock_result = MagicMock()
        mock_result.albums.results = albums
        mock_client.search.return_value = mock_result

        mocker.patch.object(provider, "_ensure_client", return_value=mock_client)

        results = provider.search("Artist", "Album")
        assert len(results) == 3


class TestDownload:
    """Test download functionality."""

    def test_download_success(self, provider, mocker):
        """Test successful download."""
        mock_popen = MagicMock()
        mock_popen.stdout = ["Line 1", "Line 2"]
        mock_popen.returncode = 0

        mocker.patch("subprocess.Popen", return_value=mock_popen)
        mocker.patch.object(provider, "_build_cmd", return_value=["cmd"])

        log_messages = []

        def log_fn(msg):
            log_messages.append(msg)

        from albfetcharr.sources.base import Match

        match = Match(
            source="yandex",
            url="https://music.yandex.ru/album/12345",
            title="Test",
            artists="Test",
            cover_url=None,
            year=None,
            track_count=None,
        )

        result = provider.download(match, log=log_fn)
        assert result is True
        assert "Downloading:" in log_messages[0]

    def test_download_failure(self, provider, mocker):
        """Test download failure."""
        mock_popen = MagicMock()
        mock_popen.stdout = ["Error line"]
        mock_popen.returncode = 1

        mocker.patch("subprocess.Popen", return_value=mock_popen)
        mocker.patch.object(provider, "_build_cmd", return_value=["cmd"])

        log_messages = []

        def log_fn(msg):
            log_messages.append(msg)

        from albfetcharr.sources.base import Match

        match = Match(
            source="yandex",
            url="https://music.yandex.ru/album/12345",
            title="Test",
            artists="Test",
            cover_url=None,
            year=None,
            track_count=None,
        )

        result = provider.download(match, log=log_fn)
        assert result is False
        assert any("failed" in msg.lower() for msg in log_messages)

    def test_download_no_log_callback(self, provider, mocker):
        """Test download with log=None (should use print)."""
        mock_popen = MagicMock()
        mock_popen.stdout = []
        mock_popen.returncode = 0

        mocker.patch("subprocess.Popen", return_value=mock_popen)
        mocker.patch.object(provider, "_build_cmd", return_value=["cmd"])
        mock_print = mocker.patch("builtins.print")

        from albfetcharr.sources.base import Match

        match = Match(
            source="yandex",
            url="https://music.yandex.ru/album/12345",
            title="Test",
            artists="Test",
            cover_url=None,
            year=None,
            track_count=None,
        )

        result = provider.download(match, log=None)
        assert result is True
        mock_print.assert_called()

    def test_download_exception(self, provider, mocker):
        """Test download with exception."""
        mocker.patch(
            "subprocess.Popen",
            side_effect=RuntimeError("Test error"),
        )
        mocker.patch.object(provider, "_build_cmd", return_value=["cmd"])

        log_messages = []

        def log_fn(msg):
            log_messages.append(msg)

        from albfetcharr.sources.base import Match

        match = Match(
            source="yandex",
            url="https://music.yandex.ru/album/12345",
            title="Test",
            artists="Test",
            cover_url=None,
            year=None,
            track_count=None,
        )

        result = provider.download(match, log=log_fn)
        assert result is False
        assert any("error" in msg.lower() for msg in log_messages)


class TestThreadSafety:
    """Test thread safety of search."""

    def test_search_serialization(self, provider, mocker):
        """Test that concurrent searches are serialized."""
        from concurrent.futures import ThreadPoolExecutor

        call_count = [0]
        max_concurrent = [0]
        current_concurrent = [0]

        def mock_search(*args, **kwargs):
            current_concurrent[0] += 1
            max_concurrent[0] = max(max_concurrent[0], current_concurrent[0])
            call_count[0] += 1

            import time

            time.sleep(0.01)
            current_concurrent[0] -= 1

            mock_result = MagicMock()
            mock_result.albums = None
            return mock_result

        mock_client = MagicMock()
        mock_client.search = mock_search
        mocker.patch.object(provider, "_ensure_client", return_value=mock_client)

        def run_search():
            provider.search("Artist", "Album")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run_search) for _ in range(8)]
            for f in futures:
                f.result()

        assert call_count[0] == 8
        assert max_concurrent[0] == 1
