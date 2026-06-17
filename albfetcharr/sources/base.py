import abc
from dataclasses import dataclass
from typing import Callable, ClassVar

LogFn = Callable[[str], None]


@dataclass
class DownloadProgress:
    """Fine-grained progress emitted by a provider during ``download()``.

    Album-level providers (Yandex, SoundCloud) download an album as one unit and
    do not report this. The YouTube Music provider, which downloads track by
    track, reports one update after each track so the UI can render a real
    per-track progress bar (instead of a single mid-download bucket) and so the
    caller can detect a *partial* album (``errors > 0`` while ``produced > 0``).
    """

    completed: int
    """Tracks finished so far (downloaded + existing + skipped + errors)."""

    total: int
    """Total tracks in the album."""

    downloaded: int = 0
    existing: int = 0
    skipped: int = 0
    errors: int = 0
    message: str = ""


ProgressFn = Callable[[DownloadProgress], None]


@dataclass
class Match:
    """Search result from a source provider."""

    source: str
    """Provider id, e.g. "yandex"."""

    url: str
    """Canonical URL of the album in the source."""

    title: str
    artists: str
    """Joined comma-separated for UI."""

    cover_url: str | None
    year: int | None
    track_count: int | None


class SourceProvider(abc.ABC):
    """Abstract base class for music source providers.

    Thread-safety contract: a provider instance lives in the global registry and may be
    called from multiple threads concurrently (plan 2 parallelizes /api/search via
    ThreadPoolExecutor). search() MUST be safe to call concurrently — but it does NOT
    have to run in parallel. Acceptable strategies:
    (a) construct stateless clients per call (e.g. yt-dlp)
    (b) hold a threading.Lock that serializes calls (e.g. Yandex, where
        yandex_music.Client + requests.Session shared state is not guaranteed thread-safe)

    download() is not required to be thread-safe — it runs serially under web's
    download_lock and single-threaded in CLI.
    """

    id: ClassVar[str]
    """Provider identifier, e.g. "yandex"."""

    name: ClassVar[str]
    """Human-readable provider name, e.g. "Yandex Music"."""

    streams_progress: ClassVar[bool] = False
    """Whether download() reports fine-grained per-unit progress via on_progress.

    True for providers that download track-by-track (YouTube Music) and emit a
    DownloadProgress per track. False (default) for providers that download an
    album as one opaque unit (Yandex, SoundCloud) — callers should not expect a
    continuous numeric progress for those and fall back to per-status buckets.
    """

    @abc.abstractmethod
    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        """Search for an album by artist and title.

        Args:
            artist: Artist name.
            album: Album title.
            limit: Maximum number of results (default 5).

        Returns:
            List of Match objects, most relevant first.
        """
        ...

    @abc.abstractmethod
    def download(
        self,
        match: Match,
        *,
        quality: str | None = None,
        log: LogFn | None = None,
        on_progress: ProgressFn | None = None,
    ) -> bool:
        """Download an album.

        Args:
            match: The Match object from search().
            quality: Quality/format string (provider-specific, e.g. "2" for Yandex,
                     or format string for yt-dlp). None uses provider defaults.
            log: Optional callback for progress lines. When None, the provider writes
                 to stdout (CLI). When supplied, web passes log_queue.put to relay
                 lines into SSE endpoint /api/download/stream.
            on_progress: Optional callback receiving a DownloadProgress after each
                 unit of work (e.g. each track) for fine-grained UI progress.
                 Providers that download an album as a single unit may ignore it.

        Returns:
            True if the album is usable (at least one track produced/existed),
            False otherwise. A *partial* album (some tracks errored but ≥1
            succeeded) still returns True — callers detect partiality from the
            DownloadProgress (errors > 0), not the bool.
        """
        ...
