"""Centralized environment variable loading for AlbFetcharr."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("albfetcharr")

# Default in-container path for the optional ytmusicapi OAuth credentials file.
# Mount your oauth.json here (or override via ALBFETCHARR_YTMUSIC_OAUTH); when the
# file is absent, search falls back to anonymous requests (today's behavior).
DEFAULT_YTMUSIC_OAUTH_FILE = "/config/ytmusic_oauth.json"


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
    path_pattern: str | None
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
    path_pattern: str = "%(artist)s/%(album)s/%(track_number)02d - %(title)s.%(ext)s"
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
    enable_youtube_music: bool = True
    enable_soundcloud: bool = True


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


def load_yandex_options() -> YandexOptions:
    """Load Yandex Music provider options from environment variables."""
    return YandexOptions(
        quality=os.environ.get("YANDEX_MUSIC_QUALITY", "2"),
        lyrics_format=os.environ.get("ALBFETCHARR_LYRICS_FORMAT", "lrc"),
        cover_resolution=os.environ.get("ALBFETCHARR_COVER_RESOLUTION", "400"),
        embed_cover=_parse_bool(os.environ.get("ALBFETCHARR_EMBED_COVER", "0")),
        skip_existing=_parse_bool(os.environ.get("ALBFETCHARR_SKIP_EXISTING", "1")),
        delay=os.environ.get("ALBFETCHARR_DELAY", "0"),
        compat_level=os.environ.get("ALBFETCHARR_COMPAT_LEVEL", "1"),
        timeout=os.environ.get("ALBFETCHARR_TIMEOUT", "20"),
        tries=os.environ.get("ALBFETCHARR_TRIES", "20"),
        retry_delay=os.environ.get("ALBFETCHARR_RETRY_DELAY", "5"),
        stick_to_artist=_parse_bool(os.environ.get("ALBFETCHARR_STICK_TO_ARTIST", "0")),
        only_music=_parse_bool(os.environ.get("ALBFETCHARR_ONLY_MUSIC", "0")),
        unsafe_path=_parse_bool(os.environ.get("ALBFETCHARR_UNSAFE_PATH", "0")),
        path_pattern=os.environ.get("ALBFETCHARR_PATH_PATTERN") or None,
        download_dir=os.environ.get("DOWNLOAD_DIR", "/downloads"),
        clear_comments=_parse_bool(os.environ.get("ALBFETCHARR_CLEAR_COMMENTS", "0")),
    )


def load_ytdlp_options() -> YtDlpOptions:
    """Load yt-dlp provider options from environment variables."""
    return YtDlpOptions(
        download_dir=os.environ.get("DOWNLOAD_DIR", "/downloads"),
        audio_format=os.environ.get("ALBFETCHARR_YTDLP_FORMAT", "flac"),
        audio_quality=_parse_int(os.environ.get("ALBFETCHARR_YTDLP_QUALITY"), default=192),
        cookies_file=os.environ.get("ALBFETCHARR_YTDLP_COOKIES") or None,
        download_retries=max(1, _parse_int(os.environ.get("ALBFETCHARR_YTDLP_RETRIES"), default=3)),
        ytmusic_oauth_file=(
            os.environ.get("ALBFETCHARR_YTMUSIC_OAUTH") or DEFAULT_YTMUSIC_OAUTH_FILE
        ),
    )


def load_lidarr_config() -> LidarrConfig:
    """Load Lidarr configuration from environment variables."""
    return LidarrConfig(
        base_url=os.environ.get("LIDARR_URL", "").rstrip("/"),
        api_key=os.environ.get("LIDARR_API_KEY", ""),
        import_path=os.environ.get("ALBFETCHARR_LIDARR_IMPORT_PATH", ""),
        library_map=os.environ.get("ALBFETCHARR_LIBRARY_MAP"),
    )


def load_ui_defaults() -> UIDefaults:
    """Load UI default settings from environment variables."""
    language = os.environ.get("ALBFETCHARR_DEFAULT_LANG", "en")
    if language not in ("en", "ru"):
        logger.warning(f"Invalid ALBFETCHARR_DEFAULT_LANG={language!r}, falling back to 'en'")
        language = "en"

    theme = os.environ.get("ALBFETCHARR_DEFAULT_THEME", "system")
    if theme not in ("system", "light", "dark"):
        logger.warning(f"Invalid ALBFETCHARR_DEFAULT_THEME={theme!r}, falling back to 'system'")
        theme = "system"

    return UIDefaults(language=language, theme=theme)


def load_app_config() -> AppConfig:
    """Load all app configuration from environment variables."""
    return AppConfig(
        lidarr=load_lidarr_config(),
        yandex_token=os.environ.get("YANDEX_MUSIC_TOKEN"),
        yandex_options=load_yandex_options(),
        ytdlp_options=load_ytdlp_options(),
        enable_youtube_music=os.environ.get("ALBFETCHARR_ENABLE_YOUTUBE_MUSIC", "1") != "0",
        enable_soundcloud=os.environ.get("ALBFETCHARR_ENABLE_SOUNDCLOUD", "1") != "0",
    )
