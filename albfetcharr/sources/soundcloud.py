"""SoundCloud source provider via yt-dlp."""

import logging
from typing import ClassVar

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


class SoundCloudProvider(SourceProvider):
    """Source provider for SoundCloud via yt-dlp."""

    id: ClassVar[str] = "soundcloud"
    name: ClassVar[str] = "SoundCloud"

    def __init__(self, opts: YtDlpOptions):
        """Initialize the SoundCloud provider.

        Args:
            opts: YtDlpOptions dataclass with download preferences.
        """
        self._opts = opts

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on SoundCloud.

        Creates a new YoutubeDL instance per call for thread safety.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results to return.

        Returns:
            List of Match objects (playlists only), most relevant first.
        """
        ydl_opts = build_ydl_opts(self._opts, search=True)
        query = f"scsearch{limit}:{artist} {album}"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)

        if not info or not info.get("entries"):
            return []

        matches = []
        for entry in info["entries"]:
            if not isinstance(entry, dict):
                continue
            match = parse_search_entry(entry, source=self.id)
            if match:
                matches.append(match)

        return matches

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
    ) -> bool:
        """Download an album from SoundCloud.

        Uses extract_info(download=True) to get the populated info_dict,
        which is needed for the tag-repair step (Task 4.5).

        Args:
            match: The Match object from search().
            quality: Format string (unused for SoundCloud; uses build_ydl_opts default).
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
