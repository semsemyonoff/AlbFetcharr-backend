"""SoundCloud source provider via yt-dlp."""

import logging
import re
from typing import ClassVar

import yt_dlp
from yt_dlp.utils import update_url_query

from albfetcharr.config import YtDlpOptions
from albfetcharr.download.locator import album_output_dir
from albfetcharr.sources.base import LogFn, Match, ProgressFn, SourceProvider
from albfetcharr.sources.ytdlp_base import (
    LogAdapter,
    build_ydl_opts,
    make_progress_hook,
    make_set_progress_hook,
    repair_tags_from_info,
)

logger = logging.getLogger(__name__)

# SoundCloud API-v2 search endpoints (reached via yt-dlp's SoundcloudSearch
# extractor, which owns the client_id machinery — see search() for why).
#   search/albums    → only sets the uploader tagged as a real album (is_album).
#   search/playlists → albums *plus* arbitrary user playlists / compilations.
_ALBUMS_ENDPOINT = "search/albums"
_PLAYLISTS_ENDPOINT = "search/playlists"

# Title separators used when an uploader names a set "Artist - Album (year)".
_TITLE_ARTIST_SEPARATORS = (" - ", " – ", " — ")

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize_query(text: str) -> str:
    """Strip punctuation and collapse whitespace for SoundCloud's full-text search.

    SoundCloud matches search terms roughly as a logical AND over tokens, so
    punctuation (e.g. the comma in a long album title) only adds noise that can
    drop the hit count to zero. Lower-casing is left to SoundCloud.
    """
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip()


def _build_queries(artist: str, album: str) -> list[str]:
    """Build SoundCloud search queries, most specific first.

    Why a ladder instead of one query: SoundCloud's search behaves like an AND
    over query tokens. A long, many-word artist name (the motivating case was a
    band with a ~10-word name) concatenated with the album title matches
    *nothing* — no set's title contains every one of those words. A shorter,
    distinctive query (album + the first few artist words) lands the right album
    at the top. We therefore try the precise query first and fall back to broader
    ones only when a query returns zero results, so an exact match wins whenever
    it exists.
    """
    album_n = _normalize_query(album)
    artist_words = _normalize_query(artist).split()

    candidates = [
        f"{album_n} {' '.join(artist_words)}",  # album + full artist
        f"{album_n} {' '.join(artist_words[:4])}",  # album + first few artist words
        album_n,  # album alone (broadest; last resort)
    ]

    out: list[str] = []
    for q in candidates:
        q = q.strip()
        if q and q not in out:
            out.append(q)
    return out


def _parse_set_item(item: dict, *, source: str) -> Match | None:
    """Parse a raw SoundCloud album/playlist API item into a Match.

    Unlike track-flat search entries, set items carry a `permalink_url` (a
    `/sets/` URL that download() resolves via yt-dlp's SoundcloudSetIE) and a
    `track_count`. The artist is taken from the *title* — SoundCloud sets the
    band name there ("Artist - Album (year)"), while `user.username` is usually
    a random re-uploader (e.g. "User 618407895") — falling back to the uploader
    only when the title has no recognizable "Artist - " prefix.
    """
    if not isinstance(item, dict):
        return None

    url = item.get("permalink_url")
    title = item.get("title")
    if not url or not title:
        return None

    artists = (item.get("user") or {}).get("username") or "Unknown"
    for sep in _TITLE_ARTIST_SEPARATORS:
        if sep in title:
            artists = title.split(sep, 1)[0].strip()
            break

    year = None
    date = item.get("release_date") or item.get("display_date")
    if isinstance(date, str) and date[:4].isdigit():
        year = int(date[:4])

    return Match(
        source=source,
        url=url,
        title=title,
        artists=artists,
        cover_url=item.get("artwork_url"),
        year=year,
        track_count=item.get("track_count"),
    )


class SoundCloudProvider(SourceProvider):
    """Source provider for SoundCloud via yt-dlp."""

    id: ClassVar[str] = "soundcloud"
    name: ClassVar[str] = "SoundCloud"

    # download() drives yt-dlp's per-entry progress hook into on_progress, so the
    # UI gets a real per-track bar instead of the bare-"downloading" 50% bucket.
    streams_progress: ClassVar[bool] = True

    def __init__(self, opts: YtDlpOptions):
        """Initialize the SoundCloud provider.

        Args:
            opts: YtDlpOptions dataclass with download preferences.
        """
        self._opts = opts

    def _fetch_collection(self, endpoint: str, query: str, limit: int) -> list[dict]:
        """Run one SoundCloud API-v2 search and return its raw `collection`.

        We deliberately do NOT use yt-dlp's `scsearch:` prefix: that maps to the
        `search/tracks` endpoint and returns individual *tracks*, never album
        sets. Instead we borrow yt-dlp's SoundcloudSearch extractor purely for
        its `_call_api`, which transparently obtains, caches, and refreshes the
        anonymous SoundCloud `client_id` (scraped from soundcloud.com, the only
        way the API is reachable without registering an app) and retries once on
        a 401/403 by re-scraping. That lets us hit the album/playlist search
        endpoints with no client_id of our own.

        A fresh YoutubeDL per call keeps this thread-safe (search may run
        concurrently across providers). Returns [] when the response carries no
        collection; genuine network/API errors propagate so the route can mark
        the provider's search as failed.

        These are yt-dlp-internal attributes (`_call_api`, `_API_V2_BASE`,
        `_HEADERS`); guarded by tests so a yt-dlp upgrade that renames them fails
        loudly rather than silently returning nothing.
        """
        ydl_opts = build_ydl_opts(self._opts, search=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ie = ydl.get_info_extractor("SoundcloudSearch")
            ie.initialize()  # resolves client_id (cache hit or scrape)
            url = update_url_query(
                ie._API_V2_BASE + endpoint,
                {"q": query, "limit": limit, "linked_partitioning": 1, "offset": 0},
            )
            response = ie._call_api(
                url, query, "Searching SoundCloud", "SoundCloud search failed", headers=ie._HEADERS
            )

        if not isinstance(response, dict):
            return []
        return [item for item in (response.get("collection") or []) if isinstance(item, dict)]

    def _search_endpoint(self, endpoint: str, queries: list[str], limit: int) -> list[dict]:
        """Try each query against `endpoint`, returning the first non-empty result.

        Empty results advance the ladder (broaden the query); errors propagate.
        """
        for query in queries:
            collection = self._fetch_collection(endpoint, query, limit)
            if collection:
                return collection
        return []

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on SoundCloud.

        Hits `search/albums` (real albums only). When the
        `soundcloud_include_playlists` option is enabled, it also queries
        `search/playlists` and appends those hits after the album hits — this
        catches releases the uploader never tagged as an album, at the cost of
        also surfacing fan compilations/mixtapes. Album results are preferred
        (listed first) and duplicates (same set URL) are dropped.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results to return.

        Returns:
            List of Match objects, most relevant first.
        """
        queries = _build_queries(artist, album)

        collection = self._search_endpoint(_ALBUMS_ENDPOINT, queries, limit)
        if self._opts.soundcloud_include_playlists:
            collection = collection + self._search_endpoint(_PLAYLISTS_ENDPOINT, queries, limit)

        matches: list[Match] = []
        seen_urls: set[str] = set()
        for item in collection:
            match = _parse_set_item(item, source=self.id)
            if match and match.url not in seen_urls:
                seen_urls.add(match.url)
                matches.append(match)
            if len(matches) >= limit:
                break

        return matches

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
        on_progress: ProgressFn | None = None,
    ) -> bool:
        """Download an album (SoundCloud set) via yt-dlp.

        The set is fetched as one yt-dlp unit, but the output directory is forced
        to the Lidarr-requested names (``match.artists`` / ``match.title``) via
        the shared ``album_output_dir`` rule — never yt-dlp's source metadata —
        so the on-disk layout matches what Lidarr's import looks up. Per-entry
        progress hooks drive ``on_progress`` for a real per-track UI bar.

        Args:
            match: The Match object; title/artists are the Lidarr names (set by
                routes), url is the SoundCloud ``/sets/`` permalink to download.
            quality: Format string (unused for SoundCloud; uses build_ydl_opts default).
            log: Optional callback for progress lines. When None, yt-dlp writes to stdout.
            on_progress: Optional per-track progress callback (DownloadProgress).

        Returns:
            True if download succeeded, False otherwise.
        """
        ydl_opts = build_ydl_opts(self._opts, search=False)

        # Override yt-dlp's %(artist)s/%(album)s directory (source metadata) with
        # the Lidarr names. For the track number, prefer the real %(track_number)s
        # but fall back to %(playlist_index)s (the 1-based position in the set):
        # SoundCloud tracks usually carry no track_number, which otherwise renders
        # as "NA - title". The comma-alternation picks the first field that's set.
        album_dir = album_output_dir(self._opts.download_dir, match.artists, match.title)
        ydl_opts["outtmpl"] = str(
            album_dir / "%(track_number,playlist_index)02d - %(title)s.%(ext)s"
        )

        hooks = []
        if log is not None:
            hooks.append(make_progress_hook(log))
            ydl_opts["logger"] = LogAdapter(log)
        if on_progress is not None:
            hooks.append(make_set_progress_hook(on_progress))
        if hooks:
            ydl_opts["progress_hooks"] = hooks

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(match.url, download=True)
        except yt_dlp.utils.YoutubeDLError as e:
            if log:
                log(f"yt-dlp download failed: {e}")
            return False

        if info is None:
            return False

        # Single pass: fill per-track title/tracknumber/missing fields and force
        # album + albumartist to the Lidarr names so the import matches.
        repair_tags_from_info(
            album_dir, info, log=log, artist_override=match.artists, album_override=match.title
        )
        return True
