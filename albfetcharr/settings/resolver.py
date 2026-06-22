"""Settings resolver — single config-resolution chokepoint.

Precedence (highest → lowest): session override → DB → env → hardcoded default.
Env vars keep working as defaults (resolve-at-read, no env→DB seed copy).

Validation runs only at PUT (API boundary), NOT here — a permissive legacy env
value must keep resolving, never raise.
"""

from __future__ import annotations

import logging
import os

from albfetcharr.config import (
    DEFAULT_YTDLP_PATH_PATTERN,
    AppConfig,
    LidarrConfig,
    UIDefaults,
    YandexOptions,
    YtDlpOptions,
    _parse_bool,
    _parse_int,
)
from albfetcharr.settings import crypto, registry, store

logger = logging.getLogger(__name__)

# str|None fields: absent values resolve to None (not ""), preserving truthiness gates.
_NULLABLE_STR_KEYS = frozenset(
    {
        "yandex_token",
        "ytmusic_client_secret",
        "library_map",
        "ytmusic_client_id",
        "ytdlp_cookies_file",
    }
)


def _coerce(setting: registry.Setting, raw: str) -> object:
    """Convert a raw string to the Python value for this setting's type.

    Never raises — a bad legacy env/default simply falls back to the setting's
    hardcoded default (or None for nullable str fields).
    """
    t = setting.type
    if t == "bool":
        return _parse_bool(raw)
    if t in ("int", "cover_resolution"):
        # cover_resolution is "original" or a positive-int string; treat as str.
        if t == "int":
            return _parse_int(raw, default=_parse_int(setting.default, default=0))
        return raw
    # str / enum: return as-is
    return raw


def resolve_value(
    setting: registry.Setting,
    session_overrides: dict[str, str] | None,
    raw_snapshot: dict[str, tuple[str, bool]],
) -> object:
    """Resolve a single setting value with full precedence chain.

    Returns the Python-typed value (bool, int, str, or None for absent nullable str).
    """
    key = setting.key

    # 1. Session override (Tier-3 keys only, caller contract).
    if session_overrides and key in session_overrides:
        return _coerce(setting, session_overrides[key])

    # 2. DB snapshot.
    if key in raw_snapshot:
        raw_db, is_secret = raw_snapshot[key]
        if is_secret:
            decrypted = crypto.decrypt(raw_db)
            if decrypted is not None:
                # Secrets stay as str; no type coercion (they're always "str" type).
                return decrypted or (None if key in _NULLABLE_STR_KEYS else "")
            # Decrypt failed — fall through to env/default.
        else:
            return _coerce(setting, raw_db)

    # 3. Environment variable.
    env_val = os.environ.get(setting.env)
    if env_val is not None:
        # Empty string on a nullable-str key → None (preserves truthiness gates).
        if not env_val and key in _NULLABLE_STR_KEYS:
            return None
        return _coerce(setting, env_val)

    # 4. Hardcoded default.
    if setting.default is None:
        return None  # unset/optional
    if not setting.default and key in _NULLABLE_STR_KEYS:
        return None
    return _coerce(setting, setting.default)


def resolve_app_config(session_overrides: dict[str, str] | None = None) -> AppConfig:
    """Build a fully-resolved AppConfig from one DB snapshot + env + defaults.

    session_overrides: {key: raw_string_value} for Tier-3 keys only.
    """
    snapshot = store.all_raw()

    def rv(key: str) -> object:
        s = registry.get(key)
        if s is None:
            raise KeyError(f"Unknown setting key: {key!r}")
        return resolve_value(s, session_overrides, snapshot)

    # Tier-5: download_dir is env-only (never in registry).
    download_dir = os.environ.get("DOWNLOAD_DIR", "/downloads")

    lidarr = LidarrConfig(
        base_url=(rv("lidarr_url") or "").rstrip("/"),  # type: ignore[arg-type]
        api_key=rv("lidarr_api_key") or "",  # type: ignore[arg-type]
        import_path=rv("lidarr_import_path") or "",  # type: ignore[arg-type]
        library_map=rv("library_map"),  # type: ignore[arg-type]
    )

    yandex_opts = YandexOptions(
        quality=str(rv("yandex_quality")),
        lyrics_format=str(rv("yandex_lyrics_format")),
        cover_resolution=str(rv("yandex_cover_resolution")),
        embed_cover=bool(rv("yandex_embed_cover")),
        skip_existing=bool(rv("yandex_skip_existing")),
        delay=str(rv("yandex_delay")),
        compat_level=str(rv("yandex_compat_level")),
        timeout=str(rv("yandex_net_timeout")),
        tries=str(rv("yandex_net_tries")),
        retry_delay=str(rv("yandex_net_retry_delay")),
        stick_to_artist=bool(rv("yandex_stick_to_artist")),
        only_music=bool(rv("yandex_only_music")),
        unsafe_path=bool(rv("yandex_unsafe_path")),
        download_dir=download_dir,
        clear_comments=bool(rv("yandex_clear_comments")),
    )

    ytdlp_opts = YtDlpOptions(
        download_dir=download_dir,
        audio_format=str(rv("ytdlp_format")),
        audio_quality=int(rv("ytdlp_quality")),  # type: ignore[arg-type]
        path_pattern=DEFAULT_YTDLP_PATH_PATTERN,
        cookies_file=rv("ytdlp_cookies_file"),  # type: ignore[arg-type]
        download_retries=max(1, int(rv("ytdlp_retries"))),  # type: ignore[arg-type]
        ytmusic_oauth_file=str(rv("ytmusic_oauth_file")),
        ytmusic_client_id=rv("ytmusic_client_id"),  # type: ignore[arg-type]
        ytmusic_client_secret=rv("ytmusic_client_secret"),  # type: ignore[arg-type]
        soundcloud_include_playlists=bool(rv("soundcloud_include_playlists")),
    )

    ui = UIDefaults(
        language=str(rv("default_lang")),
        theme=str(rv("default_theme")),
    )

    return AppConfig(
        lidarr=lidarr,
        yandex_token=rv("yandex_token"),  # type: ignore[arg-type]
        yandex_options=yandex_opts,
        ytdlp_options=ytdlp_opts,
        ui_defaults=ui,
        enable_yandex=bool(rv("enable_yandex")),
        enable_youtube_music=bool(rv("enable_youtube_music")),
        enable_soundcloud=bool(rv("enable_soundcloud")),
        log_level=str(rv("app_log_level")),
    )
