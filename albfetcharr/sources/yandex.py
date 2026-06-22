"""Yandex Music source provider."""

import subprocess
import threading
from typing import ClassVar

from yandex_music import Client

from albfetcharr.config import YandexOptions
from albfetcharr.download.locator import album_relpath
from albfetcharr.sources.base import LogFn, Match, ProgressFn, SourceProvider


class YandexMusicProvider(SourceProvider):
    """Source provider for Yandex Music."""

    id: ClassVar[str] = "yandex"
    name: ClassVar[str] = "Yandex Music"

    def __init__(self, token: str, options: YandexOptions):
        """Initialize the Yandex Music provider.

        Args:
            token: Yandex Music API token.
            options: YandexOptions dataclass with download/search preferences.
        """
        self._token = token
        self._options = options
        self._client: Client | None = None
        self._search_lock = threading.Lock()

    def _ensure_client(self) -> Client:
        """Get or create the Yandex Music client (lazy init, called under _search_lock)."""
        if self._client is None:
            self._client = Client(self._token).init()
        return self._client

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album on Yandex Music.

        Thread-safe: serializes all search calls to avoid concurrent access
        to the yandex_music.Client.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results to return.

        Returns:
            List of Match objects, most relevant first.
        """
        with self._search_lock:
            client = self._ensure_client()
            query = f"{artist} {album}"
            try:
                results = client.search(query, type_="album")
            except Exception:
                self._client = None
                raise

            if not results or not results.albums or not results.albums.results:
                return []

            # Reorder so that artist-matching results come first, then apply limit.
            # This preserves the legacy behavior of preferring an artist match over
            # the first raw result, which matters most when limit=1 (CLI / auto-download).
            artist_lower = artist.lower()
            all_ym = results.albums.results

            def _artist_match(ym_album) -> bool:
                if not ym_album.artists:
                    return False
                return any(
                    artist_lower in a.name.lower() or a.name.lower() in artist_lower
                    for a in ym_album.artists
                )

            reordered = sorted(all_ym, key=lambda a: 0 if _artist_match(a) else 1)

            matches = []
            for ym_album in reordered[:limit]:
                ym_artists = ", ".join(a.name for a in ym_album.artists) if ym_album.artists else ""
                cover_url = (
                    f"https://{ym_album.cover_uri.replace('%%', '200x200')}"
                    if ym_album.cover_uri
                    else None
                )
                release_year = ym_album.release_date[:4] if ym_album.release_date else None
                match = Match(
                    source=self.id,
                    url=f"https://music.yandex.ru/album/{ym_album.id}",
                    title=ym_album.title or "",
                    artists=ym_artists,
                    cover_url=cover_url,
                    year=int(release_year) if release_year and release_year.isdigit() else None,
                    track_count=ym_album.track_count,
                )
                matches.append(match)

            return matches

    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
        on_progress: ProgressFn | None = None,
    ) -> bool:
        """Download an album from Yandex Music.

        Args:
            match: The Match object from search().
            quality: Quality string (numeric: "0", "1", "2"). None uses provider default.
            log: Optional callback for progress lines. When None, writes to stdout.
            on_progress: Accepted for interface parity; the yandex-music-downloader
                CLI downloads the album as a single unit, so per-track progress is
                not reported and this is ignored.

        Returns:
            True if download succeeded, False otherwise.
        """
        if log is None:
            log = print

        cmd = self._build_cmd(match, quality_override=quality)
        log(f"Downloading: {match.url}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            def _drain():
                for line in proc.stdout:
                    log(line.rstrip())

            drain_thread = threading.Thread(target=_drain, daemon=True)
            drain_thread.start()
            try:
                proc.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                drain_thread.join(timeout=5)
                log("Download timed out after 1 hour")
                return False
            drain_thread.join()

            if proc.returncode == 0:
                return True
            else:
                log(f"Download failed (exit code {proc.returncode})")
                return False
        except Exception as e:
            log(f"Download error: {type(e).__name__}")
            return False

    def _build_cmd(self, match: Match, quality_override: str | None = None) -> list[str]:
        """Build yandex-music-downloader command.

        Pins ``--path-pattern`` to the Lidarr-requested artist/album (from the
        Match) as literal directory segments, keeping the tool's per-track
        ``#number - #title`` filename. The tool's default pattern derives the
        directory from Yandex's own metadata (``#album-artist/#album``), which
        can diverge from the Lidarr names and break the import match — the shared
        ``album_relpath`` rule keeps the on-disk layout identical across all
        providers. Placeholders (``#``) only appear in the file portion, so the
        sanitized literal segments are never reinterpreted.
        """
        path_pattern = f"{album_relpath(match.artists, match.title)}/#number - #title"
        cmd = [
            "yandex-music-downloader",
            "--dir",
            self._options.download_dir,
            "--path-pattern",
            path_pattern,
            "--token",
            self._token,
            "--quality",
            str(quality_override) if quality_override is not None else self._options.quality,
            "--lyrics-format",
            self._options.lyrics_format,
            "--cover-resolution",
            self._options.cover_resolution,
            "--delay",
            self._options.delay,
            "--compatibility-level",
            self._options.compat_level,
            "--timeout",
            self._options.timeout,
            "--tries",
            self._options.tries,
            "--retry-delay",
            self._options.retry_delay,
        ]

        if self._options.skip_existing:
            cmd.append("--skip-existing")
        if self._options.embed_cover:
            cmd.append("--embed-cover")
        if self._options.stick_to_artist:
            cmd.append("--stick-to-artist")
        if self._options.only_music:
            cmd.append("--only-music")
        if self._options.unsafe_path:
            cmd.append("--unsafe-path")

        cmd += ["--url", match.url]
        return cmd
