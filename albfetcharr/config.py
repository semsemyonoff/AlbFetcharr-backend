"""AlbFetcharr configuration dataclasses and env-var parsing helpers."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("albfetcharr")

# Default in-container path for the optional ytmusicapi OAuth credentials file.
# Mount your oauth.json here (or override via ALBFETCHARR_YTMUSIC_OAUTH); when the
# file is absent, search falls back to anonymous requests (today's behavior).
DEFAULT_YTMUSIC_OAUTH_FILE = "/config/ytmusic_oauth.json"

# Hardcoded yt-dlp output template — not user-configurable (free-form templates
# are tightly coupled to the Lidarr import lookup; a fixed structure is safer).
DEFAULT_YTDLP_PATH_PATTERN = "%(artist)s/%(album)s/%(track_number)02d - %(title)s.%(ext)s"


@dataclass
class YandexOptions:
    """Options for YandexMusicProvider, loaded from ALBFETCHARR_* env vars."""

    quality: str
    lyrics_format: str
    cover_resolution: str
    embed_cover: bool
    skip_existing: bool
    delay: str
    compat_level: str
    timeout: str
    tries: str
    retry_delay: str
    stick_to_artist: bool
    only_music: bool
    unsafe_path: bool
    download_dir: str
    clear_comments: bool = False


@dataclass
class LidarrConfig:
    """Lidarr connection configuration."""

    base_url: str
    api_key: str
    import_path: str
    library_map: str | None


@dataclass
class YtDlpOptions:
    """Options for yt-dlp-based providers (YouTube Music, SoundCloud)."""

    download_dir: str
    audio_format: str = "flac"
    audio_quality: int = 192
    path_pattern: str = DEFAULT_YTDLP_PATH_PATTERN
    cookies_file: str | None = None
    # Number of attempts per track on transient failures (HTTP 403, bot gate,
    # network blips). 1 means a single attempt (no retry). Configured via
    # ALBFETCHARR_YTDLP_RETRIES; also feeds yt-dlp's own retries/extractor_retries.
    download_retries: int = 3
    # Optional path to a ytmusicapi OAuth credentials file (oauth.json). When the
    # file exists, YouTube Music search/album lookups authenticate with it instead
    # of anonymous (guest) requests, which YouTube bot-gates/throttles. Configured
    # via ALBFETCHARR_YTMUSIC_OAUTH; absent/missing → anonymous (unchanged).
    ytmusic_oauth_file: str = DEFAULT_YTMUSIC_OAUTH_FILE
    ytmusic_client_id: str | None = None
    ytmusic_client_secret: str | None = None
    # SoundCloud search scope. When False (default), SoundCloud search hits only
    # the `search/albums` endpoint, which returns just sets tagged as real albums
    # (is_album=true) — clean, but it misses releases the uploader never marked as
    # an album (those are plain "playlists"/sets). When True, search additionally
    # queries `search/playlists`, catching such releases at the cost of also
    # surfacing fan-made compilations and mixtapes (e.g. a 27-track "Collection").
    # Configured via ALBFETCHARR_SOUNDCLOUD_INCLUDE_PLAYLISTS.
    soundcloud_include_playlists: bool = False


@dataclass
class UIDefaults:
    """UI default settings for language and theme."""

    language: str
    theme: str


@dataclass
class AppConfig:
    """Top-level app configuration."""

    lidarr: LidarrConfig
    yandex_token: str | None
    yandex_options: YandexOptions
    ytdlp_options: YtDlpOptions
    ui_defaults: UIDefaults = field(
        default_factory=lambda: UIDefaults(language="en", theme="system")
    )
    enable_yandex: bool = True
    enable_youtube_music: bool = True
    enable_soundcloud: bool = True
    enable_bandcamp: bool = True
    # Application log verbosity (ALBFETCHARR_LOG_LEVEL / app_log_level setting).
    log_level: str = "INFO"


def _parse_int(value: str | None, *, default: int) -> int:
    """Parse an integer env var, returning default on invalid input."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_bool(value: str | None) -> bool:
    """Parse a bool-like env var."""
    if value is None:
        return False
    return value.lower() in ("1", "true", "yes")
