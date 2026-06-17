"""Tests for YouTubeMusicProvider."""

import shutil
import subprocess
from unittest.mock import MagicMock

import pytest
import yt_dlp
from mutagen import File as MutagenFile

from albfetcharr.config import YtDlpOptions
from albfetcharr.sources.base import Match
from albfetcharr.sources.youtube_music import (
    YouTubeMusicProvider,
    _browse_id_from_url,
    _sanitize_name,
    _write_track_tags,
)


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


def _track(*, video_id="vid", title="Track", available=True, artists=(("Daft Punk", "UC1"),)):
    """Build a ytmusicapi get_album track dict (shape from real 1.11.5 output)."""
    return {
        "videoId": video_id,
        "title": title,
        "isAvailable": available,
        "artists": [{"name": n, "id": i} for n, i in artists],
    }


def _album_data(*, year="2001", title="Discovery", tracks=None):
    """Build a ytmusicapi get_album response (shape from real 1.11.5 output)."""
    if tracks is None:
        tracks = [
            _track(video_id="vid1", title="One"),
            _track(video_id="vid2", title="Two"),
        ]
    return {"title": title, "year": year, "trackCount": len(tracks), "tracks": tracks}


def _dl_match(
    url="https://music.youtube.com/browse/MPREb_abc",
    title="Lidarr Album",
    artists="Lidarr Artist",
):
    """Build a download Match carrying the browseId in url and Lidarr names."""
    return Match(
        source="youtube_music",
        url=url,
        title=title,
        artists=artists,
        cover_url=None,
        year=2001,
        track_count=2,
    )


def _mock_ytmusic(mocker, album_data):
    """Patch the YTMusic import site so get_album returns album_data."""
    mock_yt = MagicMock()
    mock_yt.get_album.return_value = album_data
    return mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)


def _mock_ydl(mocker):
    """Patch yt_dlp.YoutubeDL with a context-manager-aware mock."""
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    cls = mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)
    return cls, mock_ydl


class TestSanitizeName:
    """Test the filesystem-name sanitizer."""

    def test_strips_hostile_chars(self):
        assert _sanitize_name("AC/DC: Live?") == "ACDC Live"

    def test_collapses_whitespace(self):
        assert _sanitize_name("  a   b  ") == "a b"

    def test_empty_falls_back_to_unknown(self):
        assert _sanitize_name("///") == "Unknown"
        assert _sanitize_name("") == "Unknown"


class TestBrowseIdFromUrl:
    """Test the browseId URL parser."""

    def test_parses_browse_id(self):
        assert _browse_id_from_url("https://music.youtube.com/browse/MPREb_x") == "MPREb_x"

    def test_strips_trailing_segments(self):
        assert _browse_id_from_url("https://music.youtube.com/browse/MPREb_x/more?a=1") == "MPREb_x"

    def test_returns_none_without_marker(self):
        assert _browse_id_from_url("https://example.com/foo") is None

    def test_returns_none_for_empty(self):
        assert _browse_id_from_url(None) is None
        assert _browse_id_from_url("") is None


class TestDownload:
    """Test YouTubeMusicProvider.download() (per-track via ytmusicapi)."""

    def test_unparseable_url_returns_false(self, provider, mocker):
        """An unparseable URL returns False without touching ytmusicapi."""
        mock_cls = mocker.patch("albfetcharr.sources.youtube_music.YTMusic")
        result = provider.download(_dl_match(url="https://example.com/nope"), log=None)
        assert result is False
        mock_cls.assert_not_called()

    def test_get_album_error_returns_false(self, provider, mocker):
        """A get_album failure returns False and logs."""
        mock_yt = MagicMock()
        mock_yt.get_album.side_effect = RuntimeError("boom")
        mocker.patch("albfetcharr.sources.youtube_music.YTMusic", return_value=mock_yt)
        log_fn = MagicMock()
        assert provider.download(_dl_match(), log=log_fn) is False
        log_fn.assert_called()

    def test_zero_tracks_returns_false(self, provider, mocker):
        """An album with no tracks returns False without downloading."""
        _mock_ytmusic(mocker, _album_data(tracks=[]))
        cls, _ = _mock_ydl(mocker)
        assert provider.download(_dl_match(), log=None) is False
        cls.assert_not_called()

    def test_full_success_per_track_watch_urls(self, provider, mocker, tmp_path):
        """Each available track downloads a watch?v= URL; tags use Lidarr names."""
        provider._opts.download_dir = str(tmp_path)
        _mock_ytmusic(mocker, _album_data())
        cls, mock_ydl = _mock_ydl(mocker)
        tags = mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        assert provider.download(_dl_match(), log=None) is True

        urls = [c.args[0][0] for c in mock_ydl.download.call_args_list]
        assert urls == [
            "https://www.youtube.com/watch?v=vid1",
            "https://www.youtube.com/watch?v=vid2",
        ]
        assert tags.call_count == 2
        # Tagged path uses the POST-EXTRACTION extension (.flac) and Lidarr names.
        first_path = tags.call_args_list[0].args[0]
        assert first_path == tmp_path / "Lidarr Artist" / "Lidarr Album" / "01 - One.flac"
        kw = tags.call_args_list[0].kwargs
        assert kw["title"] == "One"
        assert kw["album"] == "Lidarr Album"
        assert kw["albumartist"] == "Lidarr Artist"
        assert kw["tracknumber"] == 1
        assert kw["date"] == "2001"

    def test_outtmpl_uses_ext_placeholder(self, provider, mocker, tmp_path):
        """outtmpl ends in .%(ext)s, never a baked extension."""
        provider._opts.download_dir = str(tmp_path)
        _mock_ytmusic(mocker, _album_data(tracks=[_track(video_id="v", title="One")]))
        cls, _ = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        provider.download(_dl_match(), log=None)

        opts = cls.call_args.args[0]
        assert opts["outtmpl"].endswith("01 - One.%(ext)s")
        assert ".flac" not in opts["outtmpl"]

    def test_unavailable_tracks_skipped_still_true(self, provider, mocker, tmp_path):
        """Missing videoId / isAvailable=False are skipped, not errors; still True."""
        provider._opts.download_dir = str(tmp_path)
        tracks = [
            _track(video_id="v1", title="One"),
            _track(video_id=None, title="Gone"),
            _track(video_id="v3", title="Region", available=False),
        ]
        _mock_ytmusic(mocker, _album_data(tracks=tracks))
        cls, mock_ydl = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        assert provider.download(_dl_match(), log=None) is True
        assert mock_ydl.download.call_count == 1

    def test_all_unavailable_returns_false(self, provider, mocker, tmp_path):
        """Zero produced tracks (all unavailable) returns False."""
        provider._opts.download_dir = str(tmp_path)
        tracks = [_track(video_id=None, title="X", available=False)]
        _mock_ytmusic(mocker, _album_data(tracks=tracks))
        cls, mock_ydl = _mock_ydl(mocker)

        assert provider.download(_dl_match(), log=None) is False
        mock_ydl.download.assert_not_called()

    def test_per_track_error_returns_false(self, provider, mocker, tmp_path):
        """A real per-track download error returns False."""
        provider._opts.download_dir = str(tmp_path)
        _mock_ytmusic(mocker, _album_data())
        cls, mock_ydl = _mock_ydl(mocker)
        mock_ydl.download.side_effect = yt_dlp.utils.DownloadError("nope")
        log_fn = MagicMock()

        assert provider.download(_dl_match(), log=log_fn) is False

    def test_skip_existing_uses_post_extraction_path(self, provider, mocker, tmp_path):
        """An existing post-extraction .flac file is skipped, not re-downloaded."""
        provider._opts.download_dir = str(tmp_path)
        album_path = tmp_path / "Lidarr Artist" / "Lidarr Album"
        album_path.mkdir(parents=True)
        (album_path / "01 - One.flac").write_bytes(b"x")
        _mock_ytmusic(mocker, _album_data())
        cls, mock_ydl = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        assert provider.download(_dl_match(), log=None) is True
        urls = [c.args[0][0] for c in mock_ydl.download.call_args_list]
        assert urls == ["https://www.youtube.com/watch?v=vid2"]

    def test_with_log_installs_hooks(self, provider, mocker, tmp_path):
        """A log callback installs progress_hooks and logger on the opts."""
        provider._opts.download_dir = str(tmp_path)
        _mock_ytmusic(mocker, _album_data(tracks=[_track(video_id="v", title="One")]))
        cls, _ = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        provider.download(_dl_match(), log=MagicMock())

        opts = cls.call_args.args[0]
        assert "progress_hooks" in opts
        assert "logger" in opts

    def test_without_log_no_hooks(self, provider, mocker, tmp_path):
        """No log callback leaves progress_hooks/logger off the opts."""
        provider._opts.download_dir = str(tmp_path)
        _mock_ytmusic(mocker, _album_data(tracks=[_track(video_id="v", title="One")]))
        cls, _ = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        provider.download(_dl_match(), log=None)

        opts = cls.call_args.args[0]
        assert "progress_hooks" not in opts
        assert "logger" not in opts

    def test_cookiefile_present_when_file_exists(self, provider, mocker, tmp_path):
        """A configured, existing cookies file adds cookiefile to the opts."""
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        provider._opts.download_dir = str(tmp_path)
        provider._opts.cookies_file = str(cookies)
        _mock_ytmusic(mocker, _album_data(tracks=[_track(video_id="v", title="One")]))
        cls, _ = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        provider.download(_dl_match(), log=None)

        opts = cls.call_args.args[0]
        assert opts["cookiefile"] == str(cookies)

    def test_no_cookiefile_when_unset(self, provider, mocker, tmp_path):
        """With no cookies configured, the opts carry no cookiefile key."""
        provider._opts.download_dir = str(tmp_path)
        provider._opts.cookies_file = None
        _mock_ytmusic(mocker, _album_data(tracks=[_track(video_id="v", title="One")]))
        cls, _ = _mock_ydl(mocker)
        mocker.patch("albfetcharr.sources.youtube_music._write_track_tags")

        provider.download(_dl_match(), log=None)

        opts = cls.call_args.args[0]
        assert "cookiefile" not in opts


class TestWriteTrackTags:
    """Round-trip the tag writer on a real audio container."""

    def test_roundtrip_all_six_tags(self, tmp_path):
        """All six tags read back from a real FLAC produced by ffmpeg."""
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg required for tag round-trip test")
        flac = tmp_path / "01 - One.flac"
        subprocess.run(
            [
                "ffmpeg",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                "0.1",
                "-c:a",
                "flac",
                "-y",
                str(flac),
            ],
            check=True,
            capture_output=True,
        )

        _write_track_tags(
            flac,
            title="One",
            artist="Daft Punk",
            album="Discovery",
            albumartist="Daft Punk",
            tracknumber=1,
            date="2001",
        )

        tags = MutagenFile(str(flac), easy=True)
        assert tags["title"] == ["One"]
        assert tags["artist"] == ["Daft Punk"]
        assert tags["album"] == ["Discovery"]
        assert tags["albumartist"] == ["Daft Punk"]
        assert tags["tracknumber"] == ["1"]
        assert tags["date"] == ["2001"]


class TestProvider:
    """Test provider identity."""

    def test_provider_id(self, provider):
        """Test that provider has correct id."""
        assert provider.id == "youtube_music"

    def test_provider_name(self, provider):
        """Test that provider has correct name."""
        assert provider.name == "YouTube Music"
