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


def _album_result(
    *,
    browse_id="MPREb_abc",
    title="Discovery",
    artists=(("Daft Punk", "UCabc"),),
    year="2001",
    thumbnails=None,
    track_count=None,
):
    """Build a ytmusicapi search album result dict (shape from real 1.11.5 output)."""
    result = {
        "category": "Albums",
        "resultType": "album",
        "title": title,
        "type": "Album",
        "browseId": browse_id,
        "year": year,
        "isExplicit": False,
        "artists": [{"name": n, "id": i} for n, i in artists],
        "thumbnails": thumbnails
        if thumbnails is not None
        else [
            {"url": "https://img/small.jpg", "width": 60, "height": 60},
            {"url": "https://img/large.jpg", "width": 544, "height": 544},
        ],
    }
    if track_count is not None:
        result["trackCount"] = track_count
    return result


class TestSearch:
    """Test YouTubeMusicProvider.search()."""

    def test_search_empty_response(self, provider, mocker):
        """Test search with empty (None) response returns []."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = None
        mock_cls = mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Artist", "Album", limit=5)

        assert results == []
        # Search builds a fresh client per call and runs an albums-filtered query.
        mock_cls.assert_called_once_with()
        mock_yt.search.assert_called_once_with("Artist Album", filter="albums", limit=5)

    def test_search_empty_list_returns_empty(self, provider, mocker):
        """Test search with an empty list returns []."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = []
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        assert provider.search("Artist", "Album", limit=5) == []

    def test_search_maps_match_fields(self, provider, mocker):
        """Album result maps to a Match with browseId in url and largest thumbnail."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = [
            _album_result(browse_id="MPREb_xyz", title="Discovery", track_count=14)
        ]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Daft Punk", "Discovery", limit=5)

        assert len(results) == 1
        match = results[0]
        assert match.source == "youtube_music"
        assert match.url == "https://music.youtube.com/browse/MPREb_xyz"
        assert match.title == "Discovery"
        assert match.artists == "Daft Punk"
        assert match.year == 2001
        assert match.track_count == 14
        assert match.cover_url == "https://img/large.jpg"

    def test_search_joins_multiple_artists(self, provider, mocker):
        """Multiple artists are joined comma-separated."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = [
            _album_result(artists=(("Daft Punk", "UC1"), ("Pharrell", "UC2")))
        ]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Daft Punk", "Album", limit=5)

        assert results[0].artists == "Daft Punk, Pharrell"

    def test_search_falls_back_to_queried_artist(self, provider, mocker):
        """When a result has no artists, fall back to the queried artist."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = [_album_result(artists=())]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Queried Artist", "Album", limit=5)

        assert results[0].artists == "Queried Artist"

    def test_search_skips_results_without_browse_id(self, provider, mocker):
        """Results lacking a browseId are dropped."""
        good = _album_result(browse_id="MPREb_good")
        bad = _album_result(browse_id=None)
        bad.pop("browseId")
        mock_yt = MagicMock()
        mock_yt.search.return_value = [bad, good]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Daft Punk", "Album", limit=5)

        assert len(results) == 1
        assert results[0].url.endswith("MPREb_good")

    def test_search_orders_artist_matches_first(self, provider, mocker):
        """Artist-matching results are ordered before non-matching ones."""
        non_match = _album_result(
            browse_id="MPREb_other", title="Other", artists=(("Some Cover Band", "UCx"),)
        )
        match = _album_result(browse_id="MPREb_real", title="Real", artists=(("Daft Punk", "UCy"),))
        mock_yt = MagicMock()
        mock_yt.search.return_value = [non_match, match]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Daft Punk", "Album", limit=5)

        assert [m.title for m in results] == ["Real", "Other"]

    def test_search_slices_to_limit(self, provider, mocker):
        """Results are sliced to the requested limit."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = [
            _album_result(browse_id=f"MPREb_{i}", title=f"Album {i}") for i in range(5)
        ]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Daft Punk", "Album", limit=2)

        assert len(results) == 2

    def test_search_missing_year_is_none(self, provider, mocker):
        """A missing/non-numeric year maps to None."""
        mock_yt = MagicMock()
        mock_yt.search.return_value = [_album_result(year=None)]
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)

        results = provider.search("Daft Punk", "Album", limit=5)

        assert results[0].year is None
        assert results[0].track_count is None


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
            "requested_downloads": [{"filepath": str(album_dir / "01.flac")}],
            "entries": [{"title": "Track 1", "artist": "Artist"}],
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

        info = {"title": "Album", "uploader": "Artist", "entries": []}

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
