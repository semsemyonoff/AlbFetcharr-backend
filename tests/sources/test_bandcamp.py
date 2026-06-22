"""Tests for BandcampProvider."""

from unittest.mock import MagicMock

import pytest
import yt_dlp

from albfetcharr.config import YtDlpOptions
from albfetcharr.download.locator import album_output_dir
from albfetcharr.sources.bandcamp import BandcampProvider, _artist_score, _cover_url
from albfetcharr.sources.base import Match


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
    """Create a BandcampProvider instance."""
    return BandcampProvider(ytdlp_options)


def _album_result(url, name, band_name, *, cover="https://f4.bcbits.com/img/a.jpg", type_="a"):
    """Build a raw Bandcamp autocomplete result like search_filter=a returns."""
    return {
        "type": type_,
        "name": name,
        "band_name": band_name,
        "item_url_path": url,
        "img": cover,
    }


def _http_response(payload):
    """Build a mock requests.Response with .json()/.raise_for_status()."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class TestArtistScore:
    """Test the _artist_score fuzzy matcher that filters tributes."""

    def test_exact_match_is_one(self):
        assert _artist_score("Boards of Canada", "Boards of Canada") == 1.0

    def test_case_and_punctuation_insensitive(self):
        assert _artist_score("M83", "m83") == 1.0

    def test_substring_scores_high(self):
        # "Beatles" is contained in "The Beatles" (and vice-versa) → kept.
        assert _artist_score("The Beatles", "Beatles") == 0.9
        assert _artist_score("Beatles", "The Beatles") == 0.9

    def test_unrelated_tribute_scores_low(self):
        # The motivating case: a fan account uploads a Radiohead tribute.
        assert _artist_score("Radiohead", "plummie") < 0.45

    def test_empty_inputs_score_zero(self):
        assert _artist_score("", "Artist") == 0.0
        assert _artist_score("Artist", "") == 0.0


class TestCoverUrl:
    """Test _cover_url — builds usable album art from art_id, not the broken img."""

    def test_builds_album_art_url_from_art_id(self):
        # Autocomplete's img (no leading 'a') 404s; art_id yields the real cover.
        item = {"art_id": 3411624925, "img": "https://f4.bcbits.com/img/3411624925_3.jpg"}
        assert _cover_url(item) == "https://f4.bcbits.com/img/a3411624925_9.jpg"

    def test_art_id_preferred_over_img(self):
        item = {"art_id": 42, "img": "https://example.com/whatever.jpg"}
        assert _cover_url(item) == "https://f4.bcbits.com/img/a42_9.jpg"

    def test_falls_back_to_img_without_art_id(self):
        assert _cover_url({"img": "http://art.jpg"}) == "http://art.jpg"

    def test_falsy_art_id_falls_back_to_img(self):
        # A 0/empty art_id is treated as absent (an "a_9.jpg" URL would be broken).
        assert _cover_url({"art_id": 0, "img": "http://art.jpg"}) == "http://art.jpg"

    def test_none_when_no_art_id_and_no_img(self):
        assert _cover_url({}) is None


class TestSearch:
    """Test BandcampProvider.search()."""

    def test_search_empty_results(self, provider, mocker):
        """No results yields no matches."""
        mocker.patch.object(provider, "_fetch_results", return_value=[])

        assert provider.search("Artist", "Album", limit=5) == []

    def test_search_parses_result_fields(self, provider, mocker):
        """Match fields come from the result: name→title, band_name→artists, img→cover."""
        item = _album_result(
            "https://artist.bandcamp.com/album/album", "Album", "Artist", cover="http://art.jpg"
        )
        mocker.patch.object(provider, "_fetch_results", return_value=[item])

        results = provider.search("Artist", "Album", limit=5)

        assert len(results) == 1
        m = results[0]
        assert m.source == "bandcamp"
        assert m.url == "https://artist.bandcamp.com/album/album"
        assert m.title == "Album"
        assert m.artists == "Artist"
        assert m.cover_url == "http://art.jpg"
        # Year/track_count are not in search results; yt-dlp fills tags at download.
        assert m.year is None
        assert m.track_count is None

    def test_search_builds_cover_from_art_id(self, provider, mocker):
        """A real result carries art_id → cover is the usable a<art_id>_16 URL."""
        item = _album_result("https://a.bandcamp.com/album/x", "Album", "Artist")
        item["art_id"] = 777
        mocker.patch.object(provider, "_fetch_results", return_value=[item])

        results = provider.search("Artist", "Album", limit=5)

        assert results[0].cover_url == "https://f4.bcbits.com/img/a777_9.jpg"

    def test_search_skips_non_album_results(self, provider, mocker):
        """Defensively drops any non-album (type != "a") entries."""
        album = _album_result("https://a.bandcamp.com/album/x", "X", "Artist")
        track = _album_result("https://a.bandcamp.com/track/y", "Y", "Artist", type_="t")
        mocker.patch.object(provider, "_fetch_results", return_value=[track, album])

        results = provider.search("Artist", "X", limit=5)

        assert [m.url for m in results] == ["https://a.bandcamp.com/album/x"]

    def test_search_drops_artist_mismatch_tribute(self, provider, mocker):
        """A hit whose band_name doesn't match the artist (a tribute) is dropped."""
        real = _album_result("https://boc.bandcamp.com/album/mhtrtc", "Album", "Boards of Canada")
        tribute = _album_result("https://plummie.bandcamp.com/album/cover", "Album", "plummie")
        mocker.patch.object(provider, "_fetch_results", return_value=[tribute, real])

        results = provider.search("Boards of Canada", "Album", limit=5)

        assert [m.artists for m in results] == ["Boards of Canada"]

    def test_search_ranks_by_artist_score(self, provider, mocker):
        """Closer artist matches rank ahead of weaker (but still kept) ones."""
        exact = _album_result("https://a.bandcamp.com/album/1", "Album", "Tame Impala")
        partial = _album_result("https://b.bandcamp.com/album/2", "Album", "Tame Impala Live")
        # API returns the weaker match first; ranking must reorder.
        mocker.patch.object(provider, "_fetch_results", return_value=[partial, exact])

        results = provider.search("Tame Impala", "Album", limit=5)

        assert results[0].url == "https://a.bandcamp.com/album/1"

    def test_search_dedupes_by_url(self, provider, mocker):
        """The same album URL is returned once."""
        item = _album_result("https://a.bandcamp.com/album/x", "X", "Artist")
        mocker.patch.object(provider, "_fetch_results", return_value=[item, dict(item)])

        results = provider.search("Artist", "X", limit=5)

        assert len(results) == 1

    def test_search_respects_limit(self, provider, mocker):
        """No more than `limit` matches are returned."""
        items = [
            _album_result(f"https://a.bandcamp.com/album/{i}", "Album", "Artist") for i in range(10)
        ]
        mocker.patch.object(provider, "_fetch_results", return_value=items)

        results = provider.search("Artist", "Album", limit=3)

        assert len(results) == 3

    def test_search_posts_album_filter_query(self, provider, mocker):
        """search() POSTs the artist+album query with the album filter."""
        post = mocker.patch(
            "albfetcharr.sources.bandcamp.requests.post",
            return_value=_http_response({"auto": {"results": []}}),
        )

        provider.search("Aphex Twin", "Drukqs", limit=5)

        post.assert_called_once()
        body = post.call_args.kwargs["json"]
        assert body["search_text"] == "Aphex Twin Drukqs"
        assert body["search_filter"] == "a"

    def test_search_exception_propagates(self, provider, mocker):
        """Search exceptions propagate for per-provider error isolation."""
        mocker.patch.object(provider, "_fetch_results", side_effect=Exception("Network error"))

        with pytest.raises(Exception, match="Network error"):
            provider.search("Artist", "Album", limit=5)

    def test_fetch_results_unexpected_shape_returns_empty(self, provider, mocker):
        """A non-dict payload yields no results rather than raising."""
        mocker.patch(
            "albfetcharr.sources.bandcamp.requests.post", return_value=_http_response([1, 2, 3])
        )

        assert provider.search("Artist", "Album", limit=5) == []


class TestDownload:
    """Test BandcampProvider.download()."""

    def _match(self):
        return Match(
            source="bandcamp",
            url="https://artist.bandcamp.com/album/album",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

    def _mock_ydl(self, mocker, *, info):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        return mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

    def test_download_success(self, provider, mocker):
        """Successful download returns True and resolves the album URL."""
        cls = self._mock_ydl(
            mocker,
            info={"title": "Album", "entries": [{"filepath": "/downloads/Artist/Album/01.flac"}]},
        )
        mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")
        match = self._match()

        assert provider.download(match, quality=None, log=None) is True
        args = cls.return_value.extract_info.call_args
        assert args[0] == (match.url,)
        assert args[1]["download"] is True

    def test_download_with_log_installs_hooks(self, provider, mocker):
        """A log callback installs progress_hooks and a logger."""
        cls = self._mock_ydl(mocker, info={"entries": []})
        mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")

        assert provider.download(self._match(), quality=None, log=MagicMock()) is True
        ydl_opts = cls.call_args[0][0]
        assert "progress_hooks" in ydl_opts
        assert "logger" in ydl_opts

    def test_download_without_log_no_hooks(self, provider, mocker):
        """Without a log callback no hooks/logger are installed."""
        cls = self._mock_ydl(mocker, info={"entries": []})
        mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")

        assert provider.download(self._match(), quality=None, log=None) is True
        ydl_opts = cls.call_args[0][0]
        assert "progress_hooks" not in ydl_opts
        assert "logger" not in ydl_opts

    def test_download_error_returns_false(self, provider, mocker):
        """A yt-dlp error returns False and logs."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError("boom")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)
        log = MagicMock()

        assert provider.download(self._match(), quality=None, log=log) is False
        log.assert_called()

    def test_download_none_info_returns_false(self, provider, mocker):
        """A None info_dict returns False."""
        self._mock_ydl(mocker, info=None)

        assert provider.download(self._match(), quality=None, log=None) is False

    def test_download_uses_lidarr_dir_for_tags(self, provider, mocker):
        """Tag repair targets the Lidarr-named dir and forces album identity."""
        info = {"title": "Some Bandcamp Title", "uploader": "label", "entries": []}
        self._mock_ydl(mocker, info=info)
        repair = mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")

        assert provider.download(self._match(), quality=None, log=None) is True
        expected_dir = album_output_dir(provider._opts.download_dir, "Artist", "Album")
        assert repair.call_args[0][0] == expected_dir
        assert repair.call_args[0][1] == info
        assert repair.call_args.kwargs == {
            "log": None,
            "artist_override": "Artist",
            "album_override": "Album",
        }

    def test_download_outtmpl_targets_lidarr_dir(self, provider, mocker):
        """The yt-dlp outtmpl directory is the Lidarr-named album dir."""
        cls = self._mock_ydl(mocker, info={"entries": []})
        mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")

        provider.download(self._match(), quality=None, log=None)
        ydl_opts = cls.call_args[0][0]
        expected_dir = album_output_dir(provider._opts.download_dir, "Artist", "Album")
        assert ydl_opts["outtmpl"] == str(
            expected_dir / "%(track_number,playlist_index)02d - %(title)s.%(ext)s"
        )

    def test_download_installs_set_progress_hook(self, provider, mocker):
        """on_progress wires a per-track progress hook into yt-dlp opts."""
        cls = self._mock_ydl(mocker, info={"entries": []})
        mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")

        provider.download(self._match(), quality=None, log=None, on_progress=lambda p: None)
        ydl_opts = cls.call_args[0][0]
        assert "progress_hooks" in ydl_opts
        assert len(ydl_opts["progress_hooks"]) == 1

    def test_streams_progress_flag(self, provider):
        """Bandcamp reports per-track progress, so the UI gets a real bar."""
        assert provider.streams_progress is True


class TestCookies:
    """The optional yt-dlp cookiefile is honored on the download path."""

    def _match(self):
        return Match(
            source="bandcamp",
            url="https://artist.bandcamp.com/album/album",
            title="Album",
            artists="Artist",
            cover_url=None,
            year=2023,
            track_count=10,
        )

    def _capture(self, mocker):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mocker.patch("albfetcharr.sources.bandcamp.repair_tags_from_info")
        return mocker.patch("yt_dlp.YoutubeDL", return_value=mock_ydl)

    def test_download_no_cookies_omits_cookiefile(self, provider, mocker):
        cls = self._capture(mocker)
        provider.download(self._match(), quality=None, log=None)
        assert "cookiefile" not in cls.call_args[0][0]

    def test_download_cookies_file_exists_adds_cookiefile(self, ytdlp_options, tmp_path, mocker):
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        ytdlp_options.cookies_file = str(cookies)
        provider = BandcampProvider(ytdlp_options)
        cls = self._capture(mocker)

        provider.download(self._match(), quality=None, log=None)
        assert cls.call_args[0][0]["cookiefile"] == str(cookies)


class TestYtDlpApiSurface:
    """Guard the yt-dlp extractor download() depends on.

    download() hands the album URL to BandcampAlbumIE; a yt-dlp upgrade that
    removes/renames it should fail here loudly rather than at download time.
    """

    def test_bandcamp_album_extractor_present(self):
        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        assert ydl.get_info_extractor("BandcampAlbum") is not None


class TestProvider:
    """Test provider identity."""

    def test_provider_id(self, provider):
        assert provider.id == "bandcamp"

    def test_provider_name(self, provider):
        assert provider.name == "Bandcamp"
