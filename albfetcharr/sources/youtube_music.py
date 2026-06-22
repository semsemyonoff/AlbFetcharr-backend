"""YouTube Music source provider.

Search uses the ``ytmusicapi`` library rather than yt-dlp's fragile YouTube-Music
search extractor. Anonymous ytmusicapi requests work but are increasingly
bot-gated/throttled by YouTube (empty results), so search optionally authenticates
via OAuth when a credentials file is configured (see ``_build_ytmusic_client``).
Downloading still uses yt-dlp.
"""

import glob
import logging
import os
from pathlib import Path, PurePosixPath
from typing import ClassVar

import yt_dlp
from mutagen import File as MutagenFile
from ytmusicapi import OAuthCredentials, YTMusic

from albfetcharr.config import YtDlpOptions
from albfetcharr.download.locator import sanitize_path_segment as _sanitize_name
from albfetcharr.settings.file_status import load_oauth_json
from albfetcharr.sources.base import DownloadProgress, LogFn, Match, ProgressFn, SourceProvider
from albfetcharr.sources.ytdlp_base import (
    LogAdapter,
    apply_cookies,
    make_progress_hook,
)

logger = logging.getLogger(__name__)

# Token fields written by ``ytmusicapi oauth`` into oauth.json. We read them back
# (plus client_id/client_secret) to authenticate the ytmusicapi client.
_OAUTH_TOKEN_KEYS = (
    "scope",
    "token_type",
    "access_token",
    "refresh_token",
    "expires_at",
    "expires_in",
)


def _build_ytmusic_client(opts: YtDlpOptions) -> YTMusic:
    """Build a ytmusicapi client, authenticated via OAuth when configured.

    Anonymous (guest) ytmusicapi requests are increasingly bot-gated/throttled by
    YouTube (empty search results). When ``opts.ytmusic_oauth_file`` points at an
    existing credentials file, authenticate with it so requests are not anonymous;
    otherwise fall back to an anonymous client (unchanged behavior).

    The file is the JSON produced by ``ytmusicapi oauth`` (token fields), optionally
    augmented with ``client_id``/``client_secret`` (the YouTube OAuth client). Those
    two may instead be supplied via ``ALBFETCHARR_YTMUSIC_CLIENT_ID`` /
    ``ALBFETCHARR_YTMUSIC_CLIENT_SECRET``. The token is passed to ytmusicapi as a
    dict (not the file path) so ytmusicapi never rewrites the user's file on refresh.
    A plain browser-headers file is also accepted (no client creds needed). Any read
    or auth error degrades to anonymous rather than breaking search.
    """
    path = opts.ytmusic_oauth_file
    if not path or not os.path.exists(path):
        return YTMusic()

    # Shared loader with oauth_file_status: returns None for unreadable, malformed,
    # or non-object JSON (e.g. ``[]``) — guarding the ``data.get(...)`` calls below
    # from an AttributeError that would escape the auth try/except entirely.
    data = load_oauth_json(path)
    if data is None:
        logger.warning(
            "Could not read YTMusic OAuth file %s (unreadable or not a JSON object); "
            "using anonymous search",
            path,
        )
        return YTMusic()

    client_id = data.get("client_id") or opts.ytmusic_client_id
    client_secret = data.get("client_secret") or opts.ytmusic_client_secret
    token = {k: data[k] for k in _OAUTH_TOKEN_KEYS if k in data}

    try:
        if token and client_id and client_secret:
            creds = OAuthCredentials(client_id=client_id, client_secret=client_secret)
            logger.debug("Using authenticated YTMusic client (OAuth) from %s", path)
            return YTMusic(token, oauth_credentials=creds)
        if token and not (client_id and client_secret):
            logger.warning(
                "YTMusic OAuth token at %s is missing client_id/client_secret "
                "(set them in the file or via ALBFETCHARR_YTMUSIC_CLIENT_ID/"
                "ALBFETCHARR_YTMUSIC_CLIENT_SECRET); using anonymous search",
                path,
            )
            return YTMusic()
        # Not an OAuth token file — treat as a ytmusicapi browser-headers file.
        logger.debug("Using authenticated YTMusic client (browser headers) from %s", path)
        return YTMusic(path)
    except Exception as e:
        logger.warning("YTMusic auth from %s failed: %s; using anonymous search", path, e)
        return YTMusic()


# yt-dlp's FFmpegExtractAudio writes a container whose extension differs from the
# codec name for a few codecs; map to the real on-disk extension so skip-existing
# and tagging resolve the actual produced file rather than a non-existent path.
_CODEC_EXT = {"aac": "m4a", "alac": "m4a", "vorbis": "ogg"}


def _audio_ext(audio_format: str) -> str:
    """Resolve the on-disk file extension produced for a yt-dlp audio codec.

    Returns ``"best"`` unchanged for the passthrough format — there the produced
    extension is only known after extraction (yt-dlp keeps the source container,
    typically ``.opus`` or ``.m4a``), so callers must resolve the real file on
    disk via ``_produced_file`` rather than assume ``stem.best``.
    """
    return _CODEC_EXT.get(audio_format, audio_format)


# yt-dlp / FFmpeg in-progress markers. ``.part`` / ``.ytdl`` are the final suffix
# of a partial download (``stem.opus.part``); ``.temp`` is an *infix* before the
# real extension in FFmpegPostProcessor's temp file (``stem.temp.opus``, whose
# final suffix is the codec, not ``.temp``). Either marks an unfinished track, so
# the whole suffix chain — not just the final suffix — is inspected.
_TEMP_MARKERS = {".part", ".ytdl", ".temp"}

# Audio container extensions yt-dlp / FFmpegExtractAudio can leave on disk. For a
# fixed codec the produced extension is deterministic; for ``best`` (passthrough)
# yt-dlp keeps the source container, so any of these may appear. A finished track
# is recognized by an allowlist of audio extensions — not by excluding known
# sidecars — so a thumbnail, lyrics (``.lrc``), subtitle, or metadata/info file
# can never be mistaken for the track, whatever extension it uses.
_AUDIO_EXTS = {
    ".opus",
    ".m4a",
    ".mp3",
    ".aac",
    ".ogg",
    ".oga",
    ".flac",
    ".wav",
    ".webm",
    ".weba",
    ".mka",
}


def _is_finished_track(candidate: Path, stem: str) -> bool:
    """True when ``candidate`` is a finished audio file, not a sidecar or temp.

    Requires a recognized audio extension (``_AUDIO_EXTS``) as the final suffix,
    so thumbnails, lyrics, subtitles, and metadata sidecars are never counted as
    the track. Also rejects yt-dlp/FFmpeg in-progress files, including the
    post-processor's ``stem.temp.opus`` whose *final* suffix is the real codec —
    hence the whole suffix chain is checked, not just the last one.

    Only the suffixes appended *after* ``stem`` are inspected; dots inside the
    track title itself (e.g. ``Song.temp`` → ``01 - Song.temp.opus``) belong to
    the stem and must not be mistaken for in-progress markers.
    """
    appended = candidate.name[len(stem) :] if candidate.name.startswith(stem) else candidate.name
    # ``appended`` starts with a dot (glob matched ``stem.*``); prefix a
    # placeholder so pathlib parses the trailing chain, not a hidden file.
    trailing = PurePosixPath("x" + appended)
    suffixes = {s.lower() for s in trailing.suffixes}
    if suffixes & _TEMP_MARKERS:
        return False
    return trailing.suffix.lower() in _AUDIO_EXTS


def _produced_file(album_path: Path, stem: str, ext: str) -> Path | None:
    """Return the produced audio file for ``stem`` on disk, or None.

    For a fixed codec the on-disk extension is deterministic, so this is a plain
    existence check on ``stem.ext``. For ``best`` (passthrough — yt-dlp keeps the
    source container, so the extension is only known after extraction) it matches
    any ``stem.*`` file with a recognized audio extension (skipping thumbnails,
    lyrics/metadata sidecars, and partial downloads).

    Used to skip already-downloaded tracks and, after a post-processing error, to
    tell a produced-then-failed track from one that never landed — both of which
    were broken for ``best`` while ``stem.best`` (a path yt-dlp never writes) was
    assumed.
    """
    if ext != "best":
        exact = album_path / f"{stem}.{ext}"
        return exact if exact.exists() else None
    if not album_path.is_dir():
        return None
    for candidate in sorted(album_path.glob(f"{glob.escape(stem)}.*")):
        if candidate.is_file() and _is_finished_track(candidate, stem):
            return candidate
    return None


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
    # Downloads track-by-track and reports a DownloadProgress per track.
    streams_progress: ClassVar[bool] = True

    def __init__(self, opts: YtDlpOptions):
        """Initialize the YouTube Music provider.

        Args:
            opts: YtDlpOptions dataclass with download preferences.
        """
        self._opts = opts

    def _ytmusic(self) -> YTMusic:
        """Create a fresh ytmusicapi client (authenticated when OAuth is configured).

        A new client per call preserves the thread-safety contract (no shared mutable
        state, no lock) and picks up OAuth credentials via ``_build_ytmusic_client``.
        """
        return _build_ytmusic_client(self._opts)

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on YouTube Music via ytmusicapi.

        Thread-safe by construction: a fresh client is created per call (no shared
        mutable state, no lock). Authenticates via OAuth when configured (see
        ``_build_ytmusic_client``) — anonymous requests are bot-gated by YouTube and
        return empty results — otherwise falls back to anonymous.

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
        yt = self._ytmusic()
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
        if opts.audio_format == "best":
            audio_pp = {"key": "FFmpegExtractAudio", "preferredcodec": "best"}
        else:
            audio_pp = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": opts.audio_format,
                "preferredquality": str(opts.audio_quality),
            }
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                audio_pp,
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
            "quiet": True,
            "no_warnings": True,
            # yt-dlp's own retry knobs: cover transient fragment/HTTP failures
            # (incl. the intermittent 403 on "unable to download video data")
            # within a single extraction, before our outer per-track retry loop
            # in download() falls back to a fresh extraction attempt.
            "retries": opts.download_retries,
            "fragment_retries": opts.download_retries,
            "extractor_retries": opts.download_retries,
        }
        apply_cookies(ydl_opts, opts)
        return ydl_opts

    def _download_track(self, video_url: str, ydl_opts: dict) -> None:
        """Run a single yt-dlp track download with retries on transient errors.

        Retries the whole extraction up to ``opts.download_retries`` times: yt-dlp's
        built-in ``retries`` handle in-extraction fragment failures, but errors like
        HTTP 403 on "unable to download video data" often only clear on a *fresh*
        extraction, which this outer loop provides. Re-raises the last error if all
        attempts fail.
        """
        attempts = max(1, self._opts.download_retries)
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                return
            except yt_dlp.utils.YoutubeDLError as e:
                last_err = e
                logger.debug(
                    "yt-dlp attempt %d/%d failed for %s: %s", attempt, attempts, video_url, e
                )
        if last_err is not None:
            raise last_err

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
        on_progress: ProgressFn | None = None,
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

        Each downloadable track is attempted up to ``opts.download_retries`` times
        (a fresh extraction per attempt) to ride out transient HTTP 403 / bot-gate
        failures; yt-dlp's own ``retries``/``extractor_retries`` cover in-extraction
        blips. When ``on_progress`` is given, a DownloadProgress is reported after
        each track (running downloaded/existing/skipped/errors counts) for a real
        per-track progress bar and so the caller can flag a *partial* album.

        Partial-album contract (*import what's available*): tracks ytmusicapi
        reports as unavailable (``isAvailable=False`` or missing ``videoId``) are
        skipped and are **not** errors. A track whose download fails after all
        retries is counted as an error but does **not** fail the whole album.
        Returns True when ≥1 track was downloaded or already existed (even if some
        tracks errored — a *partial* success the caller surfaces as a warning); an
        explicit ``partial: N/M`` summary is always logged. Returns False only on
        parse failure or zero produced tracks.

        Args:
            match: The Match from search(); url carries the browseId, title/artists
                carry the requested Lidarr album/artist names.
            quality: Unused for YouTube Music (codec/quality come from YtDlpOptions).
            log: Optional callback for progress lines. When None, writes to stdout.
            on_progress: Optional DownloadProgress callback, invoked once per track.

        Returns:
            True if at least one track was produced/existed, else False. Partial
            albums (some tracks errored) still return True — partiality is conveyed
            via on_progress' errors count, not the bool.
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
            album = self._ytmusic().get_album(browse_id)
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

        def _emit(message: str) -> None:
            """Report per-track progress to the optional on_progress callback."""
            if on_progress is None:
                return
            on_progress(
                DownloadProgress(
                    completed=idx,
                    total=total,
                    downloaded=downloaded,
                    existing=existing,
                    skipped=skipped,
                    errors=errors,
                    message=message,
                )
            )

        for idx, track in enumerate(tracks, start=1):
            video_id = track.get("videoId")
            track_title = track.get("title") or f"Track {idx}"
            if not video_id or track.get("isAvailable") is False:
                skipped += 1
                _log(f"Skipping unavailable track {idx}/{total}: {track_title}")
                _emit(f"Skipped unavailable: {track_title}")
                continue

            track_artist = _join_artists(track.get("artists")) or album_artist

            stem = f"{idx:02d} - {_sanitize_name(track_title)}"
            existing_file = _produced_file(album_path, stem, ext)
            if existing_file is not None:
                existing += 1
                _log(f"Already downloaded {idx}/{total}: {existing_file.name}")
                _emit(f"Already downloaded: {track_title}")
                continue

            outtmpl = str(album_path / f"{stem}.%(ext)s")
            ydl_opts = self._build_track_opts(outtmpl)
            if log is not None:
                ydl_opts["progress_hooks"] = [make_progress_hook(log)]
                ydl_opts["logger"] = LogAdapter(log)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            try:
                self._download_track(video_url, ydl_opts)
            except yt_dlp.utils.YoutubeDLError as e:
                # FFmpegExtractAudio writes the final file before later post-
                # processing (e.g. thumbnail embed). If the audio is already on
                # disk, a post-processing failure is non-fatal — keep and tag the
                # track rather than failing the whole album (partial contract).
                final_path = _produced_file(album_path, stem, ext)
                if final_path is None:
                    errors += 1
                    _log(f"yt-dlp failed for track {idx}/{total} ({video_id}): {e}")
                    _emit(f"Failed: {track_title}")
                    continue
                _log(f"Post-processing issue for track {idx}/{total} ({video_id}): {e}")
            else:
                # Clean success. A fixed codec's path is deterministic; for ``best``
                # the extension is only known post-extraction, so resolve the file
                # yt-dlp actually produced (it exists now) rather than guess.
                if ext == "best":
                    final_path = _produced_file(album_path, stem, ext)
                    if final_path is None:
                        errors += 1
                        _log(
                            f"yt-dlp reported success but produced no file for "
                            f"track {idx}/{total} ({video_id})"
                        )
                        _emit(f"Failed: {track_title}")
                        continue
                else:
                    final_path = album_path / f"{stem}.{ext}"

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
            _emit(f"Downloaded: {track_title}")

        produced = downloaded + existing
        _log(
            f"partial: {produced}/{total} (downloaded={downloaded} existing={existing} "
            f"skipped={skipped} errors={errors})"
        )

        # Partial-album contract: import what's available. The album is usable as
        # long as ≥1 track was produced or already existed — a per-track error no
        # longer fails the whole album (it is surfaced to the caller as a warning
        # via the final on_progress' errors count, and reflected in `partial: N/M`).
        # Only a fully empty result (zero produced) is a hard failure.
        return produced > 0
