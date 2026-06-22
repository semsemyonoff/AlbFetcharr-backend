"""Bandcamp source provider.

Bandcamp has no search extractor in yt-dlp (only album/track/user/weekly URL
extractors), but it exposes a public, key-less search API used by its own site
autocomplete. We call that directly for search, then hand the album URL to
yt-dlp's ``BandcampAlbumIE`` for download — that extractor yields a proper album
(real ``track_number``, per-track tags, cover), so the on-disk result is clean,
unlike the re-uploader soup on SoundCloud/MailRu.

The one catch is that Bandcamp's catalog is artist-self-published: a query for a
major-label release often surfaces *tributes/covers* by unrelated accounts (e.g.
"Radiohead OK Computer" → a fan's "Radiohead's OK Computer"). To avoid
auto-downloading those, search scores each hit's ``band_name`` against the
requested artist and drops clear non-matches, ranking the rest best-first.
"""

import difflib
import logging
import re
from typing import ClassVar

import requests
import yt_dlp

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

# Bandcamp's own site-search autocomplete endpoint. No API key/auth required.
# ``search_filter="a"`` restricts results to albums (other values: "t" tracks,
# "b" bands, "f" fans); each result carries name, band_name, img and the
# canonical ``item_url_path`` (an /album/ URL that BandcampAlbumIE downloads).
_SEARCH_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
_ALBUM_FILTER = "a"
_REQUEST_TIMEOUT = 20

# Album-cover URL built from a result's numeric ``art_id``. The autocomplete's
# own ``img`` field is unusable: it points at ``/img/<art_id>_3.jpg``, dropping
# the leading ``a`` that album art requires, so it 404s. Real covers live at
# ``/img/a<art_id>_<format>.jpg``; format 9 is the ~210px square art — a search
# thumbnail, in line with the other providers' cover sizes (Yandex 200px).
_ART_URL = "https://f4.bcbits.com/img/a{art_id}_9.jpg"

# Minimum artist-match score (0..1) for a hit to be kept. Bandcamp self-uploads
# use the artist's real account name, so a legitimate release matches the
# requested artist closely (exact, substring, or high token overlap); tributes
# by unrelated accounts score near zero and are dropped. Deliberately lenient so
# minor name variations ("The Beatles" vs "Beatles") survive.
_MIN_ARTIST_SCORE = 0.45

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lower-case, strip punctuation and collapse whitespace for fuzzy matching."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip().lower()


def _artist_score(requested: str, band_name: str) -> float:
    """Score how well a Bandcamp ``band_name`` matches the requested artist (0..1).

    Returns 1.0 for an exact (normalized) match, 0.9 when one name contains the
    other (handles "The Beatles" vs "Beatles"), otherwise the max of token-set
    Jaccard overlap and a character sequence ratio. Empty inputs score 0.
    """
    a, b = _normalize(requested), _normalize(band_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return max(jaccard, ratio)


def _cover_url(item: dict) -> str | None:
    """Build the album-cover URL from a result's ``art_id``.

    Bandcamp's autocomplete ``img`` field points at ``/img/<art_id>_3.jpg`` —
    missing the leading ``a`` that album art requires, so it 404s. The real
    cover is ``/img/a<art_id>_9.jpg`` (~210px square). Falls back to the raw
    ``img`` only when a result carries no ``art_id``.
    """
    art_id = item.get("art_id")
    if art_id:
        return _ART_URL.format(art_id=art_id)
    return item.get("img") or None


def _parse_result(item: dict, *, source: str) -> Match | None:
    """Parse one Bandcamp autocomplete album result into a Match.

    Only ``type == "a"`` (album) items with both a URL and name yield a Match;
    year and track_count are absent from search results (yt-dlp fills the real
    tags at download time), so they're left as None.
    """
    if not isinstance(item, dict) or item.get("type") != _ALBUM_FILTER:
        return None

    url = item.get("item_url_path") or item.get("url")
    title = item.get("name")
    if not url or not title:
        return None

    return Match(
        source=source,
        url=url,
        title=title,
        artists=item.get("band_name") or "Unknown",
        cover_url=_cover_url(item),
        year=None,
        track_count=None,
    )


class BandcampProvider(SourceProvider):
    """Source provider for Bandcamp (key-less site search + yt-dlp download)."""

    id: ClassVar[str] = "bandcamp"
    name: ClassVar[str] = "Bandcamp"

    # download() drives yt-dlp's per-entry progress hook into on_progress (the
    # album IE yields a playlist of tracks), so the UI gets a real per-track bar.
    streams_progress: ClassVar[bool] = True

    def __init__(self, opts: YtDlpOptions):
        """Initialize the Bandcamp provider.

        Args:
            opts: YtDlpOptions dataclass with download preferences.
        """
        self._opts = opts

    def _fetch_results(self, query: str) -> list[dict]:
        """Run one Bandcamp autocomplete search and return its raw album results.

        A fresh request per call keeps this thread-safe (search may run
        concurrently across providers). Returns [] on an unexpected response
        shape; transport/HTTP errors propagate so the route can mark this
        provider's search as failed (matching SoundCloud's behavior).
        """
        response = requests.post(
            _SEARCH_URL,
            json={"search_text": query, "search_filter": _ALBUM_FILTER, "full_page": False},
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        results = (payload.get("auto") or {}).get("results") or []
        return [item for item in results if isinstance(item, dict)]

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on Bandcamp.

        Hits Bandcamp's album-filtered site search, then drops hits whose
        ``band_name`` doesn't match the requested artist closely enough
        (``_MIN_ARTIST_SCORE``) — Bandcamp's catalog is dense with tributes for
        mainstream queries — and returns the rest ranked best-match first.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results to return.

        Returns:
            List of Match objects, most relevant first.
        """
        results = self._fetch_results(f"{artist} {album}")

        scored: list[tuple[float, Match]] = []
        seen_urls: set[str] = set()
        for item in results:
            match = _parse_result(item, source=self.id)
            if not match or match.url in seen_urls:
                continue
            score = _artist_score(artist, match.artists)
            if score < _MIN_ARTIST_SCORE:
                continue
            seen_urls.add(match.url)
            scored.append((score, match))

        # Stable sort by score desc preserves Bandcamp's own relevance order
        # among equally-scored hits (Python's sort is stable).
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [match for _, match in scored[:limit]]

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
        on_progress: ProgressFn | None = None,
    ) -> bool:
        """Download an album from Bandcamp via yt-dlp's BandcampAlbumIE.

        The album is fetched as one yt-dlp unit, but the output directory is
        forced to the Lidarr-requested names (``match.artists`` / ``match.title``)
        via the shared ``album_output_dir`` rule — never yt-dlp's source metadata
        — so the on-disk layout matches what Lidarr's import looks up. Per-entry
        progress hooks drive ``on_progress`` for a real per-track UI bar.

        Args:
            match: The Match object; title/artists are the Lidarr names (set by
                routes), url is the Bandcamp ``/album/`` URL to download.
            quality: Format string (unused; uses build_ydl_opts default).
            log: Optional callback for progress lines. When None, yt-dlp writes to stdout.
            on_progress: Optional per-track progress callback (DownloadProgress).

        Returns:
            True if download succeeded, False otherwise.
        """
        ydl_opts = build_ydl_opts(self._opts, search=False)

        # Override yt-dlp's %(artist)s/%(album)s directory (source metadata) with
        # the Lidarr names. Bandcamp tracks carry a real track_number; fall back
        # to %(playlist_index)s for the rare track that lacks one.
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
