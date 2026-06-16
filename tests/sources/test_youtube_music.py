"""Tests for YouTubeMusicProvider."""

from unittest.mock import MagicMock

import pytest
import yt_dlp

from albfetcharr.config import YtDlpOptions
from albfetcharr.sources.base import Match
from albfetcharr.sources.youtube_music import YouTubeMusicProvider


@pytest.fixture
def ytdlp_options():
    """Create default YtDlpOptions for testing."""
    return YtDlpOptions(
        download_dir="/downloads",
        path_pattern="%(artist)s/%(album)s/%(track_number)02d - %(title)s.%(ext)s",
        audio_format="flac",
        audio_quality=192,
    )


@pytest.fixture
def provider(ytdlp_options):
    """Create a YouTubeMusicProvider instance."""
    return YouTubeMusicProvider(ytdlp_options)


class TestSearch:
    """Test YouTubeMusicProvider.search()."""

    def test_search_empty_response(self, provider, mocker):
        """Test search with empty response."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        results = provider.search("Artist", "Album", limit=5)

        assert results == []
        mock_ydl.extract_info.assert_called_once()
        args = mock_ydl.extract_info.call_args[0]
        assert "ytmsearch5:Artist Album" in args[0]

    def test_search_returns_only_playlists(self, provider, mocker):
        """Test that search returns only playlist entries, dropping standalone tracks."""
        entries = [
            {
                "_type": "playlist",
                "url": "https://music.youtube.com/playlist?list=PL123",
                "title": "Album Title",
                "uploader": "Artist",
                "playlist_count": 10,
            },
            {
                "_type": "url",
                "url": "https://www.youtube.com/watch?v=ABC",
                "title": "Full Album Video",
                "uploader": "Artist",
            },
            {
                # Entry without URL should be filtered by parse_search_entry
                "title": "No URL Entry",
                "uploader": "Artist",
            },
        ]

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": entries}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        results = provider.search("Artist", "Album", limit=5)

        assert len(results) == 1
        assert results[0].title == "Album Title"

    def test_search_multiple_playlists(self, provider, mocker):
        """Test search returning multiple playlists."""
        entries = [
            {
                "_type": "playlist",
                "url": "https://music.youtube.com/playlist?list=PL1",
                "title": "Album 1",
                "uploader": "Artist 1",
                "release_year": 2023,
                "playlist_count": 12,
                "thumbnails": [{"url": "https://example.com/cover1.jpg"}],
            },
            {
                "_type": "playlist",
                "url": "https://music.youtube.com/playlist?list=PL2",
                "title": "Album 2",
                "uploader": "Artist 2",
                "release_year": 2024,
                "playlist_count": 10,
                "thumbnails": [{"url": "https://example.com/cover2.jpg"}],
            },
        ]

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": entries}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        results = provider.search("Artist", "Album", limit=5)

        assert len(results) == 2
        assert results[0].source == "youtube_music"
        assert results[0].title == "Album 1"
        assert results[1].title == "Album 2"

    def test_search_exception_propagates(self, provider, mocker):
        """Test that search exceptions propagate to the caller for error isolation."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("Network error")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        with pytest.raises(Exception, match="Network error"):
            provider.search("Artist", "Album", limit=5)

    def test_search_none_entries_returns_empty(self, provider, mocker):
        """Test that search with None entries returns empty list."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        results = provider.search("Artist", "Album", limit=5)

        assert results == []

    def test_search_limit_parameter(self, provider, mocker):
        """Test that search uses the limit parameter in the query."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        provider.search("Artist", "Album", limit=3)

        args = mock_ydl.extract_info.call_args[0]
        assert "ytmsearch3:" in args[0]


class TestDownload:
    """Test YouTubeMusicProvider.download()."""

    def test_download_success(self, provider, mocker):
        """Test successful download."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            "title": "Album",
            "entries": [{"filepath": "/downloads/Artist/Album/01.flac"}],
        }
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        result = provider.download(match, quality=None, log=None)

        assert result is True
        mock_ydl.extract_info.assert_called_once()
        args = mock_ydl.extract_info.call_args
        assert args[0] == (match.url,)
        assert args[1]["download"] is True

    def test_download_with_log_callback(self, provider, mocker):
        """Test download with log callback installs hooks."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )
        log_fn = MagicMock()

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        mock_ydl_class = mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        result = provider.download(match, quality=None, log=log_fn)

        assert result is True
        # Verify that progress_hooks and logger were set in the options
        # The options dict is passed as the first positional argument
        call_args = mock_ydl_class.call_args[0]
        assert len(call_args) > 0
        ydl_opts = call_args[0]
        assert "progress_hooks" in ydl_opts
        assert "logger" in ydl_opts

    def test_download_error_returns_false(self, provider, mocker):
        """Test download error returns False."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )
        log_fn = MagicMock()

        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError("Download failed")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        result = provider.download(match, quality=None, log=log_fn)

        assert result is False
        log_fn.assert_called()

    def test_download_none_info_returns_false(self, provider, mocker):
        """Test that None info_dict returns False."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        result = provider.download(match, quality=None, log=None)

        assert result is False

    def test_download_without_log_no_hooks(self, provider, mocker):
        """Test that download without log callback does not install hooks."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_class = mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        result = provider.download(match, quality=None, log=None)

        assert result is True
        # Verify that progress_hooks and logger are NOT set when log is None
        call_args = mock_ydl_class.call_args[0]
        assert len(call_args) > 0
        ydl_opts = call_args[0]
        assert "progress_hooks" not in ydl_opts
        assert "logger" not in ydl_opts


    def test_download_calls_repair_tags(self, provider, tmp_path, mocker):
        """Test that download calls repair_tags_from_info with correct arguments."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

        album_dir = tmp_path / "Artist" / "Album"
        album_dir.mkdir(parents=True)

        info = {
            "title": "Album",
            "uploader": "Artist",
            "requested_downloads": [
                {"filepath": str(album_dir / "01.flac")}
            ],
            "entries": [
                {"title": "Track 1", "artist": "Artist"}
            ]
        }

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        mock_repair = mocker.patch("albfetcharr.sources.youtube_music.repair_tags_from_info")

        result = provider.download(match, quality=None, log=None)

        assert result is True
        mock_repair.assert_called_once()
        call_args = mock_repair.call_args
        assert call_args[0][0] == album_dir
        assert call_args[0][1] == info

    def test_download_handles_missing_filepath(self, provider, mocker):
        """Test download handles missing filepath gracefully."""
        match = Match(
            source="youtube_music",
            url="https://music.youtube.com/playlist?list=PL123",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

        info = {
            "title": "Album",
            "uploader": "Artist",
            "entries": []
        }

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        mock_repair = mocker.patch("albfetcharr.sources.youtube_music.repair_tags_from_info")

        result = provider.download(match, quality=None, log=None)

        assert result is True
        mock_repair.assert_not_called()


class TestProvider:
    """Test provider identity."""

    def test_provider_id(self, provider):
        """Test that provider has correct id."""
        assert provider.id == "youtube_music"

    def test_provider_name(self, provider):
        """Test that provider has correct name."""
        assert provider.name == "YouTube Music"
