"""YouTube Music source provider via yt-dlp."""

import logging
from typing import ClassVar
from urllib.parse import quote_plus

import yt_dlp

from albfetcharr.config import YtDlpOptions
from albfetcharr.sources.base import LogFn, Match, SourceProvider
from albfetcharr.sources.ytdlp_base import (
    LogAdapter,
    album_dir_from_info,
    build_ydl_opts,
    make_progress_hook,
    parse_search_entry,
    repair_tags_from_info,
)

logger = logging.getLogger(__name__)


class YouTubeMusicProvider(SourceProvider):
    """Source provider for YouTube Music via yt-dlp."""

    id: ClassVar[str] = "youtube_music"
    name: ClassVar[str] = "YouTube Music"

    def __init__(self, opts: YtDlpOptions):
        """Initialize the YouTube Music provider.

        Args:
            opts: YtDlpOptions dataclass with download preferences.
        """
        self._opts = opts

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on YouTube Music.

        Creates a new YoutubeDL instance per call for thread safety.

        yt-dlp has no ``ytmsearch`` query prefix — the only way to reach the
        YouTube Music search is its ``YoutubeMusicSearchURL`` extractor, driven by
        a ``https://music.youtube.com/search?q=...`` URL. The ``#Albums`` fragment
        restricts results to the Albums shelf, and ``playlist_items=1-limit`` caps
        how many albums are resolved. Resolution is intentionally *not* flat: flat
        entries are bare ``browse/`` URLs with no title/track count, whereas
        resolving each album yields a playlist dict with the metadata the UI needs.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results to return.

        Returns:
            List of Match objects (album playlists), most relevant first.
        """
        query = quote_plus(f"{artist} {album}")
        url = f"https://music.youtube.com/search?q={query}#Albums"
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "playlist_items": f"1-{limit}",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info or not info.get("entries"):
            return []

        matches = []
        for entry in info["entries"]:
            if not isinstance(entry, dict) or entry.get("_type") != "playlist":
                continue
            match = parse_search_entry(entry, source=self.id)
            if not match:
                continue
            # yt-dlp prefixes the Albums-shelf title with "Album - "; strip it for
            # a clean display name.
            match.title = match.title.removeprefix("Album - ")
            # YouTube Music album playlists don't expose the artist, so
            # parse_search_entry falls back to "Unknown" — substitute the queried
            # artist, which is what the candidate-matching score compares against.
            if not entry.get("uploader"):
                match.artists = artist
            matches.append(match)

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
