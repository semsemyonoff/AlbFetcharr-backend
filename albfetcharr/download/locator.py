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
