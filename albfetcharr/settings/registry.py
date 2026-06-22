"""Settings registry — single source of truth for all configurable settings.

Defines `Setting` (what each key is) and the full catalog (Tiers 1–4).
Tier-5 env-only/bootstrap vars are intentionally absent; PUT rejects unknown keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Setting:
    """Descriptor for one configurable setting."""

    key: str
    type: str  # "str" | "int" | "bool" | "enum" | "cover_resolution"
    default: str | None  # None means unset/optional (resolves to None, not "")
    choices: list[str] | None  # populated for type="enum" only
    env: str  # environment variable name (never empty)
    scope: str  # "global" | "session"
    secret: bool
    group: str
    provider: str  # "yandex" | "ytdlp" | "lidarr" | "app" | "ui"
    min_val: int | None = field(default=None)  # for type="int" range checks
    max_val: int | None = field(default=None)
    readonly: bool = field(default=False)  # True = env/container-set; PUT rejects


# fmt: off
_CATALOG: list[Setting] = [
    # ── Tier 1 — secrets (encrypted in DB, masked in API) ──────────────────
    Setting("yandex_token",          "str",  None,    None,                          "YANDEX_MUSIC_TOKEN",                "global",  True,  "Sources",           "yandex"),
    Setting("lidarr_api_key",        "str",  "",      None,                          "LIDARR_API_KEY",                    "global",  True,  "Lidarr",            "lidarr"),
    Setting("ytmusic_client_secret", "str",  None,    None,                          "ALBFETCHARR_YTMUSIC_CLIENT_SECRET", "global",  True,  "Sources",           "ytdlp"),

    # ── Tier 2 — global, non-secret ─────────────────────────────────────────
    Setting("lidarr_url",            "str",  "",      None,                          "LIDARR_URL",                        "global",  False, "Lidarr",            "lidarr"),
    Setting("lidarr_import_path",    "str",  "",      None,                          "ALBFETCHARR_LIDARR_IMPORT_PATH",    "global",  False, "Lidarr",            "lidarr", readonly=True),
    Setting("library_map",           "str",  None,    None,                          "ALBFETCHARR_LIBRARY_MAP",           "global",  False, "Lidarr",            "lidarr", readonly=True),
    Setting("ytmusic_client_id",     "str",  None,    None,                          "ALBFETCHARR_YTMUSIC_CLIENT_ID",     "global",  False, "Sources",           "ytdlp"),
    Setting("ytmusic_oauth_file",    "str",  "/config/ytmusic_oauth.json", None,     "ALBFETCHARR_YTMUSIC_OAUTH",         "global",  False, "Sources",           "ytdlp", readonly=True),
    Setting("ytdlp_cookies_file",    "str",  None,    None,                          "ALBFETCHARR_YTDLP_COOKIES",         "global",  False, "Sources",           "ytdlp", readonly=True),
    Setting("enable_yandex",         "bool", "1",     None,                          "ALBFETCHARR_ENABLE_YANDEX",         "global",  False, "Sources",           "app"),
    Setting("enable_youtube_music",  "bool", "1",     None,                          "ALBFETCHARR_ENABLE_YOUTUBE_MUSIC",  "global",  False, "Sources",           "app"),
    Setting("enable_soundcloud",     "bool", "1",     None,                          "ALBFETCHARR_ENABLE_SOUNDCLOUD",     "global",  False, "Sources",           "app"),
    Setting("enable_bandcamp",       "bool", "1",     None,                          "ALBFETCHARR_ENABLE_BANDCAMP",       "global",  False, "Sources",           "app"),
    Setting("soundcloud_include_playlists","bool","0", None,                         "ALBFETCHARR_SOUNDCLOUD_INCLUDE_PLAYLISTS", "global", False, "Sources",      "ytdlp"),
    Setting("yandex_delay",          "int",  "0",     None,                          "ALBFETCHARR_DELAY",                 "global",  False, "Download (Yandex)", "yandex", min_val=0),
    Setting("yandex_compat_level",   "enum", "1",     ["0", "1"],                    "ALBFETCHARR_COMPAT_LEVEL",          "global",  False, "Download (Yandex)", "yandex"),
    Setting("yandex_unsafe_path",    "bool", "0",     None,                          "ALBFETCHARR_UNSAFE_PATH",           "global",  False, "Download (Yandex)", "yandex"),
    Setting("yandex_net_timeout",    "int",  "20",    None,                          "ALBFETCHARR_YANDEX_TIMEOUT",        "global",  False, "Network",           "yandex", min_val=1),
    Setting("yandex_net_tries",      "int",  "20",    None,                          "ALBFETCHARR_YANDEX_TRIES",          "global",  False, "Network",           "yandex", min_val=1),
    Setting("yandex_net_retry_delay","int",  "5",     None,                          "ALBFETCHARR_YANDEX_RETRY_DELAY",    "global",  False, "Network",           "yandex", min_val=0),
    Setting("ytdlp_retries",         "int",  "3",     None,                          "ALBFETCHARR_YTDLP_RETRIES",         "global",  False, "Download (yt-dlp)", "ytdlp", min_val=1),

    # ── Tier 3 — session-overridable (global default in DB; per-run via overrides) ─
    Setting("yandex_quality",        "enum", "2",     ["0", "1", "2"],               "YANDEX_MUSIC_QUALITY",              "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_lyrics_format",  "enum", "lrc",   ["none", "text", "lrc"],       "ALBFETCHARR_LYRICS_FORMAT",         "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_cover_resolution","cover_resolution","400",None,                  "ALBFETCHARR_COVER_RESOLUTION",      "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_embed_cover",    "bool", "0",     None,                          "ALBFETCHARR_EMBED_COVER",           "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_skip_existing",  "bool", "1",     None,                          "ALBFETCHARR_SKIP_EXISTING",         "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_only_music",     "bool", "0",     None,                          "ALBFETCHARR_ONLY_MUSIC",            "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_stick_to_artist","bool", "0",     None,                          "ALBFETCHARR_STICK_TO_ARTIST",       "session", False, "Download (Yandex)", "yandex"),
    Setting("yandex_clear_comments", "bool", "0",     None,                          "ALBFETCHARR_CLEAR_COMMENTS",        "session", False, "Download (Yandex)", "yandex"),
    Setting("ytdlp_format",          "enum", "best",  ["best", "opus", "m4a", "mp3"], "ALBFETCHARR_YTDLP_FORMAT", "session", False, "Download (yt-dlp)", "ytdlp"),
    Setting("ytdlp_quality",         "int",  "192",   None,                          "ALBFETCHARR_YTDLP_QUALITY",         "session", False, "Download (yt-dlp)", "ytdlp", min_val=0),

    # ── Tier 4 — UI prefs (global default; per-browser in localStorage) ─────
    Setting("default_lang",          "enum", "en",    ["en", "ru"],                  "ALBFETCHARR_DEFAULT_LANG",          "global",  False, "UI",                "ui"),
    Setting("default_theme",         "enum", "system",["system", "light", "dark"],   "ALBFETCHARR_DEFAULT_THEME",         "global",  False, "UI",                "ui"),

    # ── Server — process-level knobs ────────────────────────────────────────
    Setting("app_log_level",         "enum", "INFO",  ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], "ALBFETCHARR_LOG_LEVEL", "global", False, "Server", "app"),
]
# fmt: on

_BY_KEY: dict[str, Setting] = {s.key: s for s in _CATALOG}

_VALID_BOOL_STRINGS = frozenset({"0", "1", "true", "false", "yes", "no"})


def get(key: str) -> Setting | None:
    """Return the Setting for `key`, or None if not in the registry."""
    return _BY_KEY.get(key)


def all_settings() -> list[Setting]:
    """Return all settings in catalog order."""
    return list(_CATALOG)


def by_group() -> dict[str, list[Setting]]:
    """Return settings keyed by group, preserving catalog order within each group."""
    result: dict[str, list[Setting]] = {}
    for s in _CATALOG:
        result.setdefault(s.group, []).append(s)
    return result


def session_keys() -> list[str]:
    """Return keys of all session-overridable settings (Tier 3)."""
    return [s.key for s in _CATALOG if s.scope == "session"]


def is_session_key(key: str) -> bool:
    """True iff `key` is in the registry and session-scoped."""
    s = _BY_KEY.get(key)
    return s is not None and s.scope == "session"


def is_readonly(key: str) -> bool:
    """True iff `key` is in the registry and marked readonly (env/container-only)."""
    s = _BY_KEY.get(key)
    return s is not None and s.readonly


def validate_value(setting: Setting, raw: str) -> None:
    """Validate `raw` against `setting`'s type/choices/bounds.

    Raises ValueError with a clear message on invalid input.
    Called only at PUT (API boundary); resolver never calls this on env/default values.
    """
    if setting.type == "bool":
        if raw.lower() not in _VALID_BOOL_STRINGS:
            raise ValueError(
                f"{setting.key!r}: invalid boolean {raw!r}; "
                f"expected one of {sorted(_VALID_BOOL_STRINGS)}"
            )

    elif setting.type == "int":
        try:
            val = int(raw)
        except (ValueError, TypeError):
            raise ValueError(f"{setting.key!r}: invalid integer {raw!r}")
        if setting.min_val is not None and val < setting.min_val:
            raise ValueError(f"{setting.key!r}: value {val} is below minimum {setting.min_val}")
        if setting.max_val is not None and val > setting.max_val:
            raise ValueError(f"{setting.key!r}: value {val} is above maximum {setting.max_val}")

    elif setting.type == "enum":
        if raw not in (setting.choices or []):
            raise ValueError(
                f"{setting.key!r}: invalid value {raw!r}; expected one of {setting.choices}"
            )

    elif setting.type == "cover_resolution":
        # Must be "original" or a positive integer string.
        if raw != "original":
            valid = False
            try:
                valid = int(raw) > 0
            except (ValueError, TypeError):
                pass
            if not valid:
                raise ValueError(
                    f"{setting.key!r}: invalid cover resolution {raw!r}; "
                    "expected a positive integer or 'original'"
                )

    # type == "str": any string is valid
