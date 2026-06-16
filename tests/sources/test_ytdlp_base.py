"""Tests for ytdlp_base helper module."""

from pathlib import Path

from albfetcharr.config import YtDlpOptions
from albfetcharr.sources.ytdlp_base import (
    album_dir_from_info,
    build_ydl_opts,
    parse_search_entry,
)


class TestYtDlpOptions:
    """Test YtDlpOptions dataclass."""

    def test_defaults(self):
        """Test YtDlpOptions with default values."""
        opts = YtDlpOptions(download_dir="/downloads")
        assert opts.download_dir == "/downloads"
        assert opts.path_pattern == "%(artist)s/%(album)s/%(track_number)02d - %(title)s.%(ext)s"
        assert opts.audio_format == "flac"
        assert opts.audio_quality == 192

    def test_custom_values(self):
        """Test YtDlpOptions with custom values."""
        opts = YtDlpOptions(
            download_dir="/custom",
            path_pattern="custom_pattern",
            audio_format="mp3",
            audio_quality=320,
        )
        assert opts.download_dir == "/custom"
        assert opts.path_pattern == "custom_pattern"
        assert opts.audio_format == "mp3"
        assert opts.audio_quality == 320


class TestBuildYdlOpts:
    """Test build_ydl_opts function."""

    def test_search_opts(self):
        """Test that search mode returns correct options."""
        opts = YtDlpOptions(download_dir="/downloads")
        search_opts = build_ydl_opts(opts, search=True)

        assert search_opts["quiet"] is True
        assert search_opts["no_warnings"] is True
        assert search_opts["extract_flat"] == "in_playlist"
        assert search_opts["skip_download"] is True

        assert "postprocessors" not in search_opts
        assert "format" not in search_opts

    def test_download_opts_basic(self):
        """Test that download mode returns correct options."""
        opts = YtDlpOptions(download_dir="/downloads")
        download_opts = build_ydl_opts(opts, search=False)

        assert download_opts["format"] == "bestaudio/best"
        assert download_opts["writethumbnail"] is True
        assert download_opts["embedthumbnail"] is False

    def test_download_opts_outtmpl(self):
        """Test that download mode includes correct outtmpl."""
        opts = YtDlpOptions(download_dir="/downloads")
        download_opts = build_ydl_opts(opts, search=False)

        outtmpl = download_opts["outtmpl"]
        assert "/downloads/" in outtmpl
        assert "%(artist)s" in outtmpl
        assert "%(album)s" in outtmpl
        assert "%(track_number)02d" in outtmpl

    def test_download_opts_postprocessors(self):
        """Test that download mode includes correct postprocessors in order."""
        opts = YtDlpOptions(download_dir="/downloads", audio_format="mp3", audio_quality=192)
        download_opts = build_ydl_opts(opts, search=False)

        postprocessors = download_opts["postprocessors"]
        assert len(postprocessors) == 2

        assert postprocessors[0]["key"] == "FFmpegExtractAudio"
        assert postprocessors[0]["preferredcodec"] == "mp3"
        assert postprocessors[0]["preferredquality"] == 192

        assert postprocessors[1]["key"] == "FFmpegMetadata"
        assert postprocessors[1]["add_metadata"] is True

    def test_download_opts_parse_metadata(self):
        """Test that download mode includes parse_metadata mappings."""
        opts = YtDlpOptions(download_dir="/downloads")
        download_opts = build_ydl_opts(opts, search=False)

        parse_metadata = download_opts["parse_metadata"]
        assert "playlist:%(album)s" in parse_metadata
        assert "playlist_index:%(track)s" in parse_metadata


class TestParseSearchEntry:
    """Test parse_search_entry function."""

    def test_valid_entry_minimal(self):
        """Test parsing a valid entry with minimal fields."""
        entry = {
            "url": "https://music.youtube.com/playlist?list=ABC123",
            "title": "Album Title",
            "uploader": "Artist Name",
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.source == "youtube_music"
        assert match.url == "https://music.youtube.com/playlist?list=ABC123"
        assert match.title == "Album Title"
        assert match.artists == "Artist Name"
        assert match.cover_url is None
        assert match.year is None
        assert match.track_count is None

    def test_url_falls_back_to_webpage_url(self):
        """Resolved playlists (YouTube Music albums) carry the URL under
        webpage_url with url absent/None; uploader may be present-but-None."""
        entry = {
            "url": None,
            "webpage_url": "https://www.youtube.com/playlist?list=OLAK5uy_abc",
            "title": "Album - Discovery",
            "uploader": None,
            "playlist_count": 14,
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.url == "https://www.youtube.com/playlist?list=OLAK5uy_abc"
        assert match.artists == "Unknown"  # None uploader coalesced, not leaked
        assert match.track_count == 14

    def test_valid_entry_full(self):
        """Test parsing a valid entry with all fields."""
        entry = {
            "url": "https://music.youtube.com/playlist?list=ABC123",
            "title": "Album Title",
            "uploader": "Artist Name",
            "release_year": 2023,
            "playlist_count": 12,
            "thumbnails": [
                {"url": "https://example.com/small.jpg"},
                {"url": "https://example.com/large.jpg"},
            ],
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.source == "youtube_music"
        assert match.url == "https://music.youtube.com/playlist?list=ABC123"
        assert match.title == "Album Title"
        assert match.artists == "Artist Name"
        assert match.cover_url == "https://example.com/large.jpg"
        assert match.year == 2023
        assert match.track_count == 12

    def test_year_from_release_date_string(self):
        """Test that year is extracted from release_date string."""
        entry = {
            "url": "https://example.com/album",
            "title": "Album",
            "uploader": "Artist",
            "release_date": "2024-01-15",
        }
        match = parse_search_entry(entry, source="soundcloud")

        assert match is not None
        assert match.year == 2024

    def test_missing_url_returns_none(self):
        """Test that entry without url returns None."""
        entry = {
            "title": "Album Title",
            "uploader": "Artist Name",
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is None

    def test_missing_title_returns_none(self):
        """Test that entry without title returns None."""
        entry = {
            "url": "https://example.com/album",
            "uploader": "Artist Name",
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is None

    def test_empty_entry_returns_none(self):
        """Test that empty entry returns None."""
        match = parse_search_entry({}, source="youtube_music")
        assert match is None

    def test_none_entry_returns_none(self):
        """Test that None entry returns None."""
        match = parse_search_entry(None, source="youtube_music")
        assert match is None

    def test_missing_uploader_defaults_to_unknown(self):
        """Test that missing uploader defaults to 'Unknown'."""
        entry = {
            "url": "https://example.com/album",
            "title": "Album Title",
        }
        match = parse_search_entry(entry, source="soundcloud")

        assert match is not None
        assert match.artists == "Unknown"

    def test_invalid_year_string_returns_none(self):
        """Test that invalid year string is handled gracefully."""
        entry = {
            "url": "https://example.com/album",
            "title": "Album",
            "uploader": "Artist",
            "release_year": "not-a-number",
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.year is None

    def test_year_zero_treated_as_falsy(self):
        """Test that year of 0 is treated as falsy and falls back to release_date."""
        entry = {
            "url": "https://example.com/album",
            "title": "Album",
            "uploader": "Artist",
            "release_year": 0,
            "release_date": "2020-01-01",
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.year == 2020

    def test_thumbnails_empty_list(self):
        """Test that empty thumbnails list results in None cover_url."""
        entry = {
            "url": "https://example.com/album",
            "title": "Album",
            "uploader": "Artist",
            "thumbnails": [],
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.cover_url is None

    def test_thumbnails_no_url_key(self):
        """Test that thumbnail without url key is skipped."""
        entry = {
            "url": "https://example.com/album",
            "title": "Album",
            "uploader": "Artist",
            "thumbnails": [{"width": 100}],
        }
        match = parse_search_entry(entry, source="youtube_music")

        assert match is not None
        assert match.cover_url is None

    def test_source_parameter_preserved(self):
        """Test that the source parameter is correctly stored in Match."""
        entry = {
            "url": "https://soundcloud.com/playlist/abc",
            "title": "Album",
            "uploader": "Artist",
        }
        match = parse_search_entry(entry, source="soundcloud")

        assert match.source == "soundcloud"


class TestAlbumDirFromInfo:
    """Test album_dir_from_info function."""

    def test_filepath_in_requested_downloads(self):
        """Test extraction from info["requested_downloads"][0].filepath."""
        info = {"requested_downloads": [{"filepath": "/dl/Artist/Album/01.m4a"}]}
        result = album_dir_from_info(info)

        assert result == Path("/dl/Artist/Album")

    def test_filepath_in_entries(self):
        """Test extraction from info["entries"][*].filepath."""
        info = {
            "entries": [
                {"filepath": "/dl/Artist/Album/01.m4a"},
                {"filepath": "/dl/Artist/Album/02.m4a"},
            ]
        }
        result = album_dir_from_info(info)

        assert result == Path("/dl/Artist/Album")

    def test_filepath_in_entry_requested_downloads(self):
        """Test extraction from info["entries"][*].requested_downloads[0].filepath."""
        info = {
            "entries": [
                {"requested_downloads": [{"filepath": "/dl/Artist/Album/01.m4a"}]},
            ]
        }
        result = album_dir_from_info(info)

        assert result == Path("/dl/Artist/Album")

    def test_no_filepath_returns_none(self, caplog):
        """Test that None is returned when no filepath is found."""
        info = {"title": "Some Album", "entries": [{"title": "Track 1"}]}
        result = album_dir_from_info(info)

        assert result is None
        assert "Could not find filepath" in caplog.text

    def test_empty_info_returns_none(self, caplog):
        """Test that None is returned for empty info_dict."""
        result = album_dir_from_info({})

        assert result is None

    def test_none_info_returns_none(self):
        """Test that None is returned for None input."""
        result = album_dir_from_info(None)

        assert result is None

    def test_prefers_requested_downloads_over_entries(self):
        """Test that requested_downloads is preferred over entries."""
        info = {
            "requested_downloads": [{"filepath": "/dl/Artist1/Album1/01.m4a"}],
            "entries": [
                {"filepath": "/dl/Artist2/Album2/01.m4a"},
            ],
        }
        result = album_dir_from_info(info)

        assert result == Path("/dl/Artist1/Album1")

    def test_skips_non_dict_entries(self):
        """Test that non-dict entries are skipped."""
        info = {
            "entries": [
                "not a dict",
                {"filepath": "/dl/Artist/Album/01.m4a"},
            ]
        }
        result = album_dir_from_info(info)

        assert result == Path("/dl/Artist/Album")
