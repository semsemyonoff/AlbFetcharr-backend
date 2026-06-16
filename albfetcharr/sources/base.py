import abc
from dataclasses import dataclass
from typing import Callable, ClassVar

LogFn = Callable[[str], None]


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
    ) -> bool:
        """Download an album.

        Args:
            match: The Match object from search().
            quality: Quality/format string (provider-specific, e.g. "2" for Yandex,
                     or format string for yt-dlp). None uses provider defaults.
            log: Optional callback for progress lines. When None, the provider writes
                 to stdout (CLI). When supplied, web passes log_queue.put to relay
                 lines into SSE endpoint /api/download/stream.

        Returns:
            True if download succeeded, False otherwise.
        """
        ...
