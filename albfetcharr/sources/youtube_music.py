"""YouTube Music source provider.

Search uses the ``ytmusicapi`` library (reliable, no auth) rather than yt-dlp's
fragile YouTube-Music search extractor. Downloading still uses yt-dlp.
"""

import logging
from typing import ClassVar

import yt_dlp
from ytmusicapi import YTMusic

from albfetcharr.config import YtDlpOptions
from albfetcharr.sources.base import LogFn, Match, SourceProvider
from albfetcharr.sources.ytdlp_base import (
    LogAdapter,
    album_dir_from_info,
    build_ydl_opts,
    make_progress_hook,
    repair_tags_from_info,
)

logger = logging.getLogger(__name__)


def _largest_thumbnail(thumbnails: list[dict] | None) -> str | None:
    """Return the URL of the highest-resolution thumbnail, or None."""
    if not thumbnails:
        return None
    best = max(thumbnails, key=lambda t: t.get("width") or 0)
    return best.get("url")


class YouTubeMusicProvider(SourceProvider):
    """Source provider for YouTube Music (ytmusicapi search + yt-dlp download)."""

    id: ClassVar[str] = "youtube_music"
    name: ClassVar[str] = "YouTube Music"

    def __init__(self, opts: YtDlpOptions):
        """Initialize the YouTube Music provider.

        Args:
            opts: YtDlpOptions dataclass with download preferences.
        """
        self._opts = opts

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on YouTube Music via ytmusicapi.

        Thread-safe by construction: a fresh ``YTMusic()`` client is created per
        call (no auth required for search, no shared mutable state, no lock).

        Each album result becomes an album-level Match whose ``url`` carries the
        YouTube Music ``browseId`` (``https://music.youtube.com/browse/<browseId>``)
        so ``download()`` can re-resolve the album track list. Results whose artist
        matches the query (lowercase substring, either direction) are ordered first,
        mirroring the Yandex provider, then sliced to ``limit``.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results to return.

        Returns:
            List of Match objects (albums), artist-matching results first.
        """
        yt = YTMusic()
        results = yt.search(f"{artist} {album}", filter="albums", limit=limit)
        if not results:
            return []

        artist_lower = artist.lower()

        def _artist_match(result: dict) -> bool:
            for a in result.get("artists") or []:
                name = (a.get("name") or "").lower()
                if name and (artist_lower in name or name in artist_lower):
                    return True
            return False

        reordered = sorted(results, key=lambda r: 0 if _artist_match(r) else 1)

        matches = []
        for result in reordered[:limit]:
            browse_id = result.get("browseId")
            if not browse_id:
                continue
            names = [a.get("name") for a in (result.get("artists") or []) if a.get("name")]
            artists = ", ".join(names) if names else artist
            year = result.get("year")
            track_count = result.get("trackCount")
            matches.append(
                Match(
                    source=self.id,
                    url=f"https://music.youtube.com/browse/{browse_id}",
                    title=result.get("title") or "",
                    artists=artists,
                    cover_url=_largest_thumbnail(result.get("thumbnails")),
                    year=int(year) if year and str(year).isdigit() else None,
                    track_count=int(track_count) if track_count else None,
                )
            )

        return matches

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
    ) -> bool:
        """Download an album from YouTube Music.

        Uses extract_info(download=True) to get the populated info_dict,
        which is needed for the tag-repair step (Task 4.5).

        Args:
            match: The Match object from search().
            quality: Format string (unused for YouTube Music; uses build_ydl_opts default).
            log: Optional callback for progress lines. When None, yt-dlp writes to stdout.

        Returns:
            True if download succeeded, False otherwise.
        """
        ydl_opts = build_ydl_opts(self._opts, search=False)

        if log is not None:
            ydl_opts["progress_hooks"] = [make_progress_hook(log)]
            ydl_opts["logger"] = LogAdapter(log)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(match.url, download=True)
        except yt_dlp.utils.YoutubeDLError as e:
            if log:
                log(f"yt-dlp download failed: {e}")
            return False

        if info is None:
            return False

        album_dir = album_dir_from_info(info)
        if album_dir is None:
            return True

        repair_tags_from_info(album_dir, info, log=log)
        return True
