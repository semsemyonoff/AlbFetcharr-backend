"""YouTube Music source provider.

Search uses the ``ytmusicapi`` library (reliable, no auth) rather than yt-dlp's
fragile YouTube-Music search extractor. Downloading still uses yt-dlp.
"""

import logging
import re
from pathlib import Path
from typing import ClassVar

import yt_dlp
from mutagen import File as MutagenFile
from ytmusicapi import YTMusic

from albfetcharr.config import YtDlpOptions
from albfetcharr.sources.base import LogFn, Match, SourceProvider
from albfetcharr.sources.ytdlp_base import (
    LogAdapter,
    apply_cookies,
    make_progress_hook,
)

logger = logging.getLogger(__name__)

# Characters that are illegal or hostile in filesystem path segments.
_FS_HOSTILE = re.compile(r'[/\\<>:"|?*\x00-\x1f]')

# yt-dlp's FFmpegExtractAudio writes a container whose extension differs from the
# codec name for a few codecs; map to the real on-disk extension so skip-existing
# and tagging resolve the actual produced file rather than a non-existent path.
_CODEC_EXT = {"aac": "m4a", "alac": "m4a", "vorbis": "ogg"}


def _audio_ext(audio_format: str) -> str:
    """Resolve the on-disk file extension produced for a yt-dlp audio codec."""
    return _CODEC_EXT.get(audio_format, audio_format)


def _largest_thumbnail(thumbnails: list[dict] | None) -> str | None:
    """Return the URL of the highest-resolution thumbnail, or None."""
    if not thumbnails:
        return None
    best = max(thumbnails, key=lambda t: t.get("width") or 0)
    return best.get("url")


def _join_artists(items: list[dict] | None) -> str:
    """Join ytmusicapi artist entries into a comma-separated display string."""
    return ", ".join(a.get("name") for a in (items or []) if a.get("name"))


def _album_artist(album: dict | None, tracks: list[dict]) -> str:
    """Best-effort album artist from ytmusicapi metadata.

    Prefers the album-level ``artists``; falls back to the first track that
    carries an artist. Used only when the Match has no requested (Lidarr) artist
    — i.e. the CLI ``download URL`` path — so the on-disk folder and tags reflect
    the real album rather than collapsing to ``Unknown``.
    """
    names = _join_artists((album or {}).get("artists"))
    if names:
        return names
    for track in tracks:
        names = _join_artists(track.get("artists"))
        if names:
            return names
    return ""


def _sanitize_name(name: str) -> str:
    """Sanitize a string for use as a single filesystem path segment.

    Strips filesystem-hostile characters (``/ \\ < > : " | ? *`` and control
    chars) and collapses runs of whitespace. Distinct from
    ``locator.normalize_name`` (which is for *matching*, not output paths);
    this preserves case and most punctuation so on-disk names stay readable.
    """
    cleaned = _FS_HOSTILE.sub("", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Strip leading/trailing dots so segments like "." / ".." can't escape the
    # download root (path traversal) or create hidden directories.
    cleaned = cleaned.strip(".").strip()
    return cleaned or "Unknown"


def _browse_id_from_url(url: str | None) -> str | None:
    """Parse the YouTube Music ``browseId`` from a Match URL.

    Match URLs are ``https://music.youtube.com/browse/<browseId>``; returns the
    segment after ``/browse/`` (stripped of any trailing path/query), or None
    when the URL is empty or has no ``/browse/`` marker.
    """
    if not url:
        return None
    marker = "/browse/"
    idx = url.find(marker)
    if idx == -1:
        return None
    browse_id = url[idx + len(marker) :].split("/")[0].split("?")[0].strip()
    return browse_id or None


def _write_track_tags(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    albumartist: str,
    tracknumber: int,
    date: str | int | None,
    log: LogFn | None = None,
) -> None:
    """Write clean tags onto a downloaded track with mutagen (easy mode).

    Overrides whatever junk metadata the source video carried. The final file
    path (``.<audio_format>``) must be resolved by the caller — never the
    yt-dlp ``outtmpl`` string, whose extension is the download container.
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)
        else:
            logger.info(msg)

    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception as e:
        _log(f"Could not open tags for {path.name}: {e}")
        return
    if tags is None:
        _log(f"Unsupported audio format for tagging: {path.name}")
        return

    tags["title"] = [title]
    tags["artist"] = [artist]
    tags["album"] = [album]
    tags["albumartist"] = [albumartist]
    tags["tracknumber"] = [str(tracknumber)]
    if date:
        tags["date"] = [str(date)]

    try:
        tags.save()
    except Exception as e:
        _log(f"Failed to save tags for {path.name}: {e}")


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
            artists = _join_artists(result.get("artists")) or artist
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

    def _build_track_opts(self, outtmpl: str) -> dict:
        """Build yt-dlp options for a single-track YouTube video download.

        ``outtmpl`` must end in ``.%(ext)s`` (never a baked extension): the
        download-container ext differs from the post-extraction one produced by
        FFmpegExtractAudio. The optional cookiefile is applied when configured.
        """
        opts = self._opts
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": opts.audio_format,
                    "preferredquality": str(opts.audio_quality),
                },
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
            "quiet": True,
            "no_warnings": True,
        }
        apply_cookies(ydl_opts, opts)
        return ydl_opts

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
    ) -> bool:
        """Download an album from YouTube Music, one track at a time.

        Resolves the album track list from ``match.url``'s ``browseId`` via
        ytmusicapi, then downloads each available track as an individual
        ``youtube.com/watch?v=<id>`` video (far more robust than resolving the
        YouTube-Music album playlist). Clean tags are written from the ytmusicapi
        metadata after each track.

        Folder/album identity uses the **requested Lidarr names** carried on the
        Match (``match.artists`` / ``match.title``), not the ytmusicapi album
        metadata, so the on-disk ``<artist>/<album>/`` layout matches the exact
        strings ``find_album_dir`` / ``check_album_status`` look albums up by. When
        the Match carries no names (the CLI ``download URL`` path, which has no
        Lidarr context) the provider falls back to the ytmusicapi album
        title/artist so tracks never collapse into ``Unknown/Unknown``.

        Partial-album contract (*import what's available*): tracks ytmusicapi
        reports as unavailable (``isAvailable=False`` or missing ``videoId``) are
        skipped and are **not** errors. Returns True when ≥1 track was downloaded
        or already existed and no *downloadable* track errored; an explicit
        ``partial: N/M`` summary is always logged. Returns False on parse failure,
        zero tracks, or a real per-track download error.

        Args:
            match: The Match from search(); url carries the browseId, title/artists
                carry the requested Lidarr album/artist names.
            quality: Unused for YouTube Music (codec/quality come from YtDlpOptions).
            log: Optional callback for progress lines. When None, writes to stdout.

        Returns:
            True if at least one track was produced and none errored, else False.
        """

        def _log(msg: str) -> None:
            if log:
                log(msg)
            else:
                logger.info(msg)

        browse_id = _browse_id_from_url(match.url)
        if not browse_id:
            _log(
                f"Unsupported YouTube URL for download: {match.url!r}. Direct download "
                "expects a YouTube Music album URL (music.youtube.com/browse/<id>); "
                "watch/playlist URLs are not supported — use the wanted/search flow."
            )
            return False

        try:
            album = YTMusic().get_album(browse_id)
        except Exception as e:
            _log(f"Failed to fetch album {browse_id}: {e}")
            return False

        tracks = (album or {}).get("tracks") or []
        total = len(tracks)
        if total == 0:
            _log(f"No tracks found for album {browse_id}")
            return False

        year = (album or {}).get("year")

        # Folder/album identity normally uses the requested Lidarr names carried on
        # the Match (web/wanted flow). The CLI `download URL` path has no Lidarr
        # names (empty title/artists), so fall back to the ytmusicapi album
        # metadata there — otherwise tracks would land under "Unknown/Unknown" with
        # empty album tags. When the Match carries names they always win.
        album_title = match.title or (album or {}).get("title") or ""
        album_artist = match.artists or _album_artist(album, tracks)

        artist_seg = _sanitize_name(album_artist)
        album_seg = _sanitize_name(album_title)
        album_path = Path(self._opts.download_dir) / artist_seg / album_seg
        ext = _audio_ext(self._opts.audio_format)

        downloaded = existing = skipped = errors = 0

        for idx, track in enumerate(tracks, start=1):
            video_id = track.get("videoId")
            track_title = track.get("title") or f"Track {idx}"
            if not video_id or track.get("isAvailable") is False:
                skipped += 1
                _log(f"Skipping unavailable track {idx}/{total}: {track_title}")
                continue

            track_artist = _join_artists(track.get("artists")) or album_artist

            stem = f"{idx:02d} - {_sanitize_name(track_title)}"
            final_path = album_path / f"{stem}.{ext}"
            if final_path.exists():
                existing += 1
                _log(f"Already downloaded {idx}/{total}: {final_path.name}")
                continue

            outtmpl = str(album_path / f"{stem}.%(ext)s")
            ydl_opts = self._build_track_opts(outtmpl)
            if log is not None:
                ydl_opts["progress_hooks"] = [make_progress_hook(log)]
                ydl_opts["logger"] = LogAdapter(log)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
            except yt_dlp.utils.YoutubeDLError as e:
                # FFmpegExtractAudio writes the final file before later post-
                # processing (e.g. thumbnail embed). If the audio is already on
                # disk, a post-processing failure is non-fatal — keep and tag the
                # track rather than failing the whole album (partial contract).
                if not final_path.exists():
                    errors += 1
                    _log(f"yt-dlp failed for track {idx}/{total} ({video_id}): {e}")
                    continue
                _log(f"Post-processing issue for track {idx}/{total} ({video_id}): {e}")

            _write_track_tags(
                final_path,
                title=track_title,
                artist=track_artist,
                album=album_title,
                albumartist=album_artist,
                tracknumber=idx,
                date=year,
                log=log,
            )
            downloaded += 1

        produced = downloaded + existing
        _log(
            f"partial: {produced}/{total} (downloaded={downloaded} existing={existing} "
            f"skipped={skipped} errors={errors})"
        )

        if errors:
            return False
        return produced > 0
