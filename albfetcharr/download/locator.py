"""Album location and status checking with fuzzy filesystem matching."""

import re
from pathlib import Path
from typing import Callable

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"}


def normalize_name(name: str) -> str:
    """Normalize name for filesystem comparison: strip punctuation, collapse whitespace."""
    name = name.lower()
    name = re.sub(r"[\W_]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


# Filesystem-hostile characters for a single path segment: path separators, the
# Windows-reserved set, and control chars.
_FS_HOSTILE = re.compile(r'[/\\<>:"|?*\x00-\x1f]')


def sanitize_path_segment(name: str) -> str:
    """Sanitize a string for use as a single filesystem path segment.

    Strips filesystem-hostile characters and collapses whitespace, then strips
    leading/trailing dots so segments like "." / ".." can't escape the download
    root (path traversal) or create hidden directories. Preserves case and most
    punctuation so on-disk names stay readable. Distinct from ``normalize_name``
    (which is for fuzzy *matching*, not output paths).
    """
    cleaned = _FS_HOSTILE.sub("", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(".").strip()
    # A name of only dots/spaces can survive the above as "" or "." / ". ." —
    # both are path-relative tokens that would collapse the segment into its
    # parent (escaping the download root). Fall back to a safe literal.
    if not cleaned or set(cleaned) <= {".", " "}:
        return "Unknown"
    return cleaned


def album_relpath(artist: str, album: str) -> str:
    """Return the ``<artist>/<album>`` album directory, relative and sanitized.

    The single shared rule for an album's on-disk location. ``artist`` and
    ``album`` MUST be the Lidarr-requested names (carried on the download
    ``Match``), never the source's own metadata: ``find_album_dir`` /
    ``check_album_status`` / ``post_import_cleanup`` and Lidarr's ManualImport
    all key off the Lidarr names, so a directory derived from source metadata (a
    SoundCloud set title, a romanized YouTube name, a Yandex spelling) fails to
    match and the import reports "found N files but none matched an
    artist/album". Returned with POSIX separators (the download targets are
    POSIX containers / patterns).
    """
    return f"{sanitize_path_segment(artist)}/{sanitize_path_segment(album)}"


def album_output_dir(download_dir: str, artist: str, album: str) -> Path:
    """Absolute album directory ``<download_dir>/<artist>/<album>`` (see album_relpath).

    Derived from ``album_relpath`` so the sanitize rule lives in exactly one
    place. ``album_relpath`` returns POSIX ``artist/album``; ``Path`` splits it
    into the two segments (download targets are POSIX).
    """
    return Path(download_dir) / album_relpath(artist, album)


def find_album_dir(download_dir: str, artist: str, album: str) -> Path | None:
    """Find album directory in downloads. Returns path if exists."""
    base = Path(download_dir)
    if not base.exists():
        return None
    norm_artist = normalize_name(artist)

    artist_dir = None
    for d in base.iterdir():
        if d.is_dir() and normalize_name(d.name) == norm_artist:
            artist_dir = d
            break
    if artist_dir is None:
        return None

    norm_album = normalize_name(album)
    for album_dir in artist_dir.iterdir():
        if not album_dir.is_dir():
            continue
        if (
            norm_album in normalize_name(album_dir.name)
            or normalize_name(album_dir.name) in norm_album
        ):
            return album_dir
    return None


def check_album_status(
    download_dir: str,
    artist: str,
    album: str,
    track_count_fetcher: Callable[[], int],
) -> str:
    """Check download status of an album.

    Args:
        download_dir: Directory where albums are downloaded.
        artist: Artist name.
        album: Album name.
        track_count_fetcher: Callable that returns expected track count from Lidarr.

    Returns:
        "missing", "incomplete", or "complete".
    """
    album_dir = find_album_dir(download_dir, artist, album)
    if album_dir is None:
        return "missing"

    downloaded = [f for f in album_dir.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS]
    if not downloaded:
        return "missing"

    expected = track_count_fetcher()
    if expected == 0:
        # Lidarr has no track metadata yet; files exist so treat as incomplete
        # rather than re-downloading from scratch on every run.
        return "incomplete"
    if len(downloaded) < expected:
        return "incomplete"

    return "complete"
