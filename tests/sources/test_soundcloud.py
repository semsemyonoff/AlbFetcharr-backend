"""Tests for SoundCloudProvider."""

from unittest.mock import MagicMock

import pytest
import yt_dlp

from albfetcharr.config import YtDlpOptions
from albfetcharr.download.locator import album_output_dir
from albfetcharr.sources.base import Match
from albfetcharr.sources.soundcloud import SoundCloudProvider


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
    """Create a SoundCloudProvider instance."""
    return SoundCloudProvider(ytdlp_options)


def _album_item(url, title, *, user="someuser", tracks=10, date="2018-11-15T00:00:00Z", cover="c"):
    """Build a raw SoundCloud API set item like search/albums returns."""
    return {
        "permalink_url": url,
        "title": title,
        "user": {"username": user},
        "track_count": tracks,
        "release_date": date,
        "artwork_url": cover,
    }


class TestSearch:
    """Test SoundCloudProvider.search()."""

    def test_search_empty_response(self, provider, mocker):
        """Empty collections across the query ladder yield no matches."""
        fetch = mocker.patch.object(provider, "_fetch_collection", return_value=[])

        results = provider.search("Artist", "Album", limit=5)

        assert results == []
        # All ladder queries tried against the albums endpoint.
        assert fetch.call_args_list[0].args[0] == "search/albums"

    def test_search_hits_albums_endpoint_only_by_default(self, provider, mocker):
        """Default (include_playlists off) queries only search/albums."""
        item = _album_item("https://soundcloud.com/u/sets/album", "Artist - Album (2018)")
        fetch = mocker.patch.object(provider, "_fetch_collection", return_value=[item])

        results = provider.search("Artist", "Album", limit=5)

        assert len(results) == 1
        assert results[0].title == "Artist - Album (2018)"
        assert all(call.args[0] == "search/albums" for call in fetch.call_args_list)

    def test_search_parses_set_fields(self, provider, mocker):
        """Match fields come from the set item: artist from title, year from date."""
        item = _album_item(
            "https://soundcloud.com/u/sets/album",
            "The Band - Greatest Hits (2018)",
            user="User 618407895",
            tracks=6,
            cover="http://art.jpg",
        )
        mocker.patch.object(provider, "_fetch_collection", return_value=[item])

        results = provider.search("The Band", "Greatest Hits", limit=5)

        m = results[0]
        assert m.url == "https://soundcloud.com/u/sets/album"
        assert m.artists == "The Band"  # from title, not the junk uploader
        assert m.year == 2018
        assert m.track_count == 6
        assert m.cover_url == "http://art.jpg"

    def test_search_query_ladder_broadens_on_empty(self, provider, mocker):
        """A zero-result query advances to a broader one; first non-empty wins."""
        item = _album_item("https://soundcloud.com/u/sets/a", "Band - 1917 (2018)")
        # First (longest) query empty, second returns a hit.
        fetch = mocker.patch.object(provider, "_fetch_collection", side_effect=[[], [item], []])

        results = provider.search(
            "Кобыла и Трупоглазые Жабы Искали Цезию, Нашли Поздно Утром Свистящего Хна",
            "1917",
            limit=5,
        )

        assert len(results) == 1
        # Stopped after the second query produced results (3rd not called).
        assert fetch.call_count == 2

    def test_search_includes_playlists_when_enabled(self, ytdlp_options, mocker):
        """With the option on, playlist hits are appended after album hits."""
        ytdlp_options.soundcloud_include_playlists = True
        provider = SoundCloudProvider(ytdlp_options)

        album = _album_item("https://soundcloud.com/u/sets/album", "Band - Album")
        playlist = _album_item("https://soundcloud.com/v/sets/mix", "Band Collection")

        def fake_fetch(endpoint, query, limit):
            return [album] if endpoint == "search/albums" else [playlist]

        mocker.patch.object(provider, "_fetch_collection", side_effect=fake_fetch)

        results = provider.search("Band", "Album", limit=5)

        assert [m.title for m in results] == ["Band - Album", "Band Collection"]

    def test_search_dedupes_by_url(self, ytdlp_options, mocker):
        """The same set URL from albums and playlists is returned once."""
        ytdlp_options.soundcloud_include_playlists = True
        provider = SoundCloudProvider(ytdlp_options)

        item = _album_item("https://soundcloud.com/u/sets/album", "Band - Album")
        mocker.patch.object(provider, "_fetch_collection", return_value=[item])

        results = provider.search("Band", "Album", limit=5)

        assert len(results) == 1

    def test_search_respects_limit(self, provider, mocker):
        """No more than `limit` matches are returned."""
        items = [
            _album_item(f"https://soundcloud.com/u/sets/a{i}", f"Band - A{i}") for i in range(10)
        ]
        mocker.patch.object(provider, "_fetch_collection", return_value=items)

        results = provider.search("Band", "Album", limit=3)

        assert len(results) == 3

    def test_search_exception_propagates(self, provider, mocker):
        """Search exceptions propagate to the caller for per-provider error isolation."""
        mocker.patch.object(provider, "_fetch_collection", side_effect=Exception("Network error"))

        with pytest.raises(Exception, match="Network error"):
            provider.search("Artist", "Album", limit=5)


class TestDownload:
    """Test SoundCloudProvider.download()."""

    def test_download_success(self, provider, mocker):
        """Test successful download."""
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
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
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
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
        call_args = mock_ydl_class.call_args[0]
        assert len(call_args) > 0
        ydl_opts = call_args[0]
        assert "progress_hooks" in ydl_opts
        assert "logger" in ydl_opts

    def test_download_error_returns_false(self, provider, mocker):
        """Test download error returns False."""
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
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
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
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
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
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

    def test_download_uses_lidarr_dir_for_tags(self, provider, mocker):
        """download() repairs tags on the Lidarr-named dir, forcing album identity.

        The directory is derived from the Match (Lidarr names), NOT the source's
        own metadata in info — so a SoundCloud set title in info is irrelevant.
        The Lidarr names are passed as overrides for album/albumartist.
        """
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/uploader/sets/xyz",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )
        # Source metadata title differs from the Lidarr name — must be ignored.
        info = {"title": "Some Set Title (2018)", "uploader": "User 618407895", "entries": []}

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

        mock_repair = mocker.patch("albfetcharr.sources.soundcloud.repair_tags_from_info")

        result = provider.download(match, quality=None, log=None)

        expected_dir = album_output_dir(provider._opts.download_dir, "Artist", "Album")
        assert result is True
        mock_repair.assert_called_once()
        assert mock_repair.call_args[0][0] == expected_dir
        assert mock_repair.call_args[0][1] == info
        assert mock_repair.call_args.kwargs == {
            "log": None,
            "artist_override": "Artist",
            "album_override": "Album",
        }

    def test_download_outtmpl_targets_lidarr_dir(self, provider, mocker):
        """The yt-dlp outtmpl directory is the Lidarr-named album dir."""
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/uploader/sets/xyz",
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
        mocker.patch("albfetcharr.sources.soundcloud.repair_tags_from_info")

        provider.download(match, quality=None, log=None)

        ydl_opts = mock_ydl_class.call_args[0][0]
        expected_dir = album_output_dir(provider._opts.download_dir, "Artist", "Album")
        # Track number falls back to playlist position (SoundCloud tracks lack track_number).
        assert ydl_opts["outtmpl"] == str(
            expected_dir / "%(track_number,playlist_index)02d - %(title)s.%(ext)s"
        )

    def test_download_installs_set_progress_hook(self, provider, mocker):
        """on_progress wires a per-track progress hook into yt-dlp opts."""
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/uploader/sets/xyz",
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
        mocker.patch("albfetcharr.sources.soundcloud.repair_tags_from_info")

        provider.download(match, quality=None, log=None, on_progress=lambda p: None)

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert "progress_hooks" in ydl_opts
        assert len(ydl_opts["progress_hooks"]) == 1

    def test_streams_progress_flag(self, provider):
        """SoundCloud reports per-track progress, so the UI gets a real bar."""
        assert provider.streams_progress is True


class TestCookies:
    """Test that the optional cookiefile is honored transparently.

    SoundCloud builds its yt-dlp opts via the shared build_ydl_opts(), which calls
    apply_cookies() on both the search and download branches. These tests assert
    the no-cookies default is byte-for-byte unchanged and that a cookiefile is
    added only when a configured file actually exists on disk.
    """

    def _capture_ydl_opts(self, mocker):
        """Patch yt_dlp.YoutubeDL and return the mock class to inspect ydl_opts.

        Configures the search path (get_info_extractor → _call_api → empty
        collection) and the download path (extract_info) so search() and
        download() both complete and the ydl_opts passed to YoutubeDL can be
        inspected.
        """
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ie = MagicMock()
        mock_ie._API_V2_BASE = "https://api-v2.soundcloud.com/"
        mock_ie._HEADERS = {}
        mock_ie._call_api.return_value = {"collection": []}
        mock_ydl.get_info_extractor.return_value = mock_ie
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        return mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

    def test_search_no_cookies_omits_cookiefile(self, provider, mocker):
        """No cookies configured: search opts carry no cookiefile key."""
        mock_ydl_class = self._capture_ydl_opts(mocker)

        provider.search("Artist", "Album", limit=5)

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert "cookiefile" not in ydl_opts

    def test_download_no_cookies_omits_cookiefile(self, provider, mocker):
        """No cookies configured: download opts carry no cookiefile key."""
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )
        mock_ydl_class = self._capture_ydl_opts(mocker)

        provider.download(match, quality=None, log=None)

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert "cookiefile" not in ydl_opts

    def test_download_cookies_set_but_missing_omits_cookiefile(self, ytdlp_options, mocker):
        """Cookies path configured but the file does not exist: no cookiefile added."""
        ytdlp_options.cookies_file = "/nonexistent/cookies.txt"
        provider = SoundCloudProvider(ytdlp_options)
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )
        mock_ydl_class = self._capture_ydl_opts(mocker)

        provider.download(match, quality=None, log=None)

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert "cookiefile" not in ydl_opts

    def test_download_cookies_file_exists_adds_cookiefile(self, ytdlp_options, tmp_path, mocker):
        """Configured cookies file that exists is added as cookiefile to download opts."""
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        ytdlp_options.cookies_file = str(cookies)
        provider = SoundCloudProvider(ytdlp_options)
        match = Match(
            source="soundcloud",
            url="https://soundcloud.com/artist/sets/album",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )
        mock_ydl_class = self._capture_ydl_opts(mocker)

        provider.download(match, quality=None, log=None)

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert ydl_opts["cookiefile"] == str(cookies)

    def test_search_cookies_file_exists_adds_cookiefile(self, ytdlp_options, tmp_path, mocker):
        """Configured cookies file that exists is added as cookiefile to search opts."""
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        ytdlp_options.cookies_file = str(cookies)
        provider = SoundCloudProvider(ytdlp_options)
        mock_ydl_class = self._capture_ydl_opts(mocker)

        provider.search("Artist", "Album", limit=5)

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert ydl_opts["cookiefile"] == str(cookies)


class TestYtDlpApiSurface:
    """Guard the yt-dlp-internal attributes _fetch_collection relies on.

    search() borrows the SoundcloudSearch extractor's `_call_api`, `_API_V2_BASE`
    and `_HEADERS` to reach the album/playlist endpoints. These are private, so a
    yt-dlp upgrade that renames them should fail here loudly rather than silently
    returning no results.
    """

    def test_soundcloud_search_extractor_exposes_expected_api(self):
        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        ie = ydl.get_info_extractor("SoundcloudSearch")
        assert hasattr(ie, "_call_api")
        assert isinstance(ie._API_V2_BASE, str) and ie._API_V2_BASE
        assert hasattr(ie, "_HEADERS")


class TestProvider:
    """Test provider identity."""

    def test_provider_id(self, provider):
        """Test that provider has correct id."""
        assert provider.id == "soundcloud"

    def test_provider_name(self, provider):
        """Test that provider has correct name."""
        assert provider.name == "SoundCloud"
