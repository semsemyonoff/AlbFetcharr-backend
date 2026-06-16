"""Shared helper for yt-dlp-based source providers (YouTube Music, SoundCloud)."""

import logging
from pathlib import Path

from mutagen import File as MutagenFile

from albfetcharr.config import YtDlpOptions
from albfetcharr.download.locator import AUDIO_EXTENSIONS
from albfetcharr.sources.base import LogFn, Match

logger = logging.getLogger(__name__)


def make_progress_hook(log: LogFn):
    """Create a progress hook for yt-dlp that calls the log callback."""

    def hook(info: dict):
        if info["status"] == "downloading":
            percent = info.get("_percent_str", "N/A")
            speed = info.get("_speed_str", "N/A")
            log(f"Downloaded {percent} at {speed}")
        elif info["status"] == "finished":
            log(f"Downloaded: {info.get('filename', 'unknown')}")

    return hook


class LogAdapter:
    """Adapter to convert yt-dlp logger calls to the log callback."""

    def __init__(self, log: LogFn):
        self._log = log

    def debug(self, msg, *args, **kwargs):
        if args:
            msg = msg % args
        logger.debug(msg)

    def info(self, msg, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(msg)

    def warning(self, msg, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(f"WARNING: {msg}")

    def error(self, msg, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(f"ERROR: {msg}")


def build_ydl_opts(opts: YtDlpOptions, *, search: bool) -> dict:
    """Build yt-dlp options dict for search or download.

    Args:
        opts: YtDlpOptions dataclass.
        search: If True, return options for search (no download).
                If False, return options for download with postprocessors.

    Returns:
        Dictionary suitable for YoutubeDL.__init__.
    """
    if search:
        return {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }

    return {
        "format": "bestaudio/best",
        "outtmpl": str(Path(opts.download_dir) / opts.path_pattern),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": opts.audio_format,
                "preferredquality": opts.audio_quality,
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
        ],
        "writethumbnail": True,
        "embedthumbnail": False,
        "parse_metadata": [
            "playlist:%(album)s",
            "playlist_index:%(track)s",
        ],
    }


def parse_search_entry(entry: dict, *, source: str) -> Match | None:
    """Parse a yt-dlp search entry into a Match object.

    Args:
        entry: A dictionary from YoutubeDL.extract_info(..., download=False)["entries"].
        source: Provider id (e.g. "youtube_music", "soundcloud").

    Returns:
        Match object, or None if required fields are missing.
    """
    if not entry or not isinstance(entry, dict):
        return None

    # Flat search entries (SoundCloud) expose the album under "url"; fully resolved
    # playlists (YouTube Music album search) carry it as "webpage_url" with "url"
    # absent or None.
    url = entry.get("url") or entry.get("webpage_url")
    title = entry.get("title")
    # "uploader" may be present-but-None on resolved YouTube Music playlists, so a
    # plain dict default would leak None into Match.artists — coalesce instead.
    uploader = entry.get("uploader") or "Unknown"
    year = entry.get("release_year") or entry.get("release_date")
    track_count = entry.get("playlist_count")

    if not url or not title:
        return None

    if isinstance(year, str):
        try:
            year = int(year[:4])
        except (ValueError, TypeError):
            year = None

    cover_url = None
    thumbnails = entry.get("thumbnails", [])
    if thumbnails:
        cover_url = thumbnails[-1].get("url")

    return Match(
        source=source,
        url=url,
        title=title,
        artists=uploader,
        cover_url=cover_url,
        year=year,
        track_count=track_count,
    )


def album_dir_from_info(info: dict) -> Path | None:
    """Extract the album directory from yt-dlp's info_dict.

    Prefers `info["requested_downloads"][0]["filepath"]` if present,
    otherwise searches `info["entries"][*].filepath` or
    `entries[*].requested_downloads[0].filepath`.
    Returns the parent directory (album folder) or None if no filepath is found.

    Args:
        info: The info_dict returned by yt_dlp.YoutubeDL.extract_info(..., download=True).

    Returns:
        Path to the album directory, or None if no filepath is found.
    """
    if not info:
        return None

    if "requested_downloads" in info and info["requested_downloads"]:
        first_requested = info["requested_downloads"][0]
        if isinstance(first_requested, dict) and "filepath" in first_requested:
            return Path(first_requested["filepath"]).parent

    if "entries" in info and info["entries"]:
        for entry in info["entries"]:
            if not isinstance(entry, dict):
                continue
            if "filepath" in entry:
                return Path(entry["filepath"]).parent
            if "requested_downloads" in entry and entry["requested_downloads"]:
                first_requested = entry["requested_downloads"][0]
                if isinstance(first_requested, dict) and "filepath" in first_requested:
                    return Path(first_requested["filepath"]).parent

    logger.warning("Could not find filepath in yt-dlp info_dict; tag repair skipped")
    return None


def repair_tags_from_info(album_dir: Path, info_dict: dict, log: LogFn | None = None) -> None:
    """Repair missing or incomplete tags in audio files from yt-dlp metadata.

    Iterates over audio files in album_dir and ensures that each has the required
    tags (artist, album, title, tracknumber). Missing fields are filled from:
    - info_dict["entries"][i] (for per-track fields)
    - info_dict (for album-level fields)
    - filename position (for tracknumber as fallback)

    Args:
        album_dir: Path to the directory containing downloaded audio files.
        info_dict: The info_dict from yt_dlp.YoutubeDL.extract_info(..., download=True).
        log: Optional callback for progress/repair messages.
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)
        else:
            logger.info(msg)

    if not album_dir.exists():
        _log(f"Album directory does not exist: {album_dir}")
        return

    audio_files = sorted([f for f in album_dir.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS])

    if not audio_files:
        _log(f"No audio files found in {album_dir}")
        return

    entries = info_dict.get("entries", [])
    album_title = info_dict.get("title", "")

    for file_idx, audio_file in enumerate(audio_files):
        try:
            tags = MutagenFile(str(audio_file), easy=True)
        except Exception as e:
            _log(f"Could not open tags for {audio_file.name}: {e}")
            continue

        if tags is None:
            _log(f"Unsupported audio format: {audio_file.name}")
            continue

        repaired = []
        track_entry = (
            entries[file_idx]
            if file_idx < len(entries) and isinstance(entries[file_idx], dict)
            else None
        )

        if not tags.get("artist"):
            if track_entry and track_entry.get("artist"):
                artist = track_entry["artist"]
            else:
                artist = info_dict.get("uploader", "Unknown")
            tags["artist"] = [artist]
            repaired.append(f"artist={artist}")

        if not tags.get("album"):
            tags["album"] = [album_title]
            repaired.append(f"album={album_title}")

        if not tags.get("title"):
            if track_entry and track_entry.get("title"):
                title = track_entry["title"]
            else:
                title = audio_file.stem
            tags["title"] = [title]
            repaired.append(f"title={title}")

        if not tags.get("tracknumber"):
            tracknumber = str(file_idx + 1)
            tags["tracknumber"] = [tracknumber]
            repaired.append(f"tracknumber={tracknumber}")

        if repaired:
            try:
                tags.save()
                _log(f"Repaired {audio_file.name}: {', '.join(repaired)}")
            except Exception as e:
                _log(f"Failed to save tags for {audio_file.name}: {e}")
