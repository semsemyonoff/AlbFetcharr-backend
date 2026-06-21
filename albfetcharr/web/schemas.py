"""Pydantic v2 models for AlbFetcharr API request/response validation."""

from pydantic import BaseModel, ConfigDict, RootModel, field_validator

from albfetcharr.settings import registry as _registry


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: str


class VersionResponse(BaseModel):
    """``GET /api/version`` — service version plus bundled downloader versions."""

    model_config = ConfigDict(extra="ignore")

    albfetcharr: str  # build-time APP_VERSION (OpenAPI info.version)
    yt_dlp: str  # installed yt-dlp version
    ymd: str  # installed yandex-music-downloader version


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_quality: int
    default_lang: str
    default_theme: str
    import_enabled: bool
    encryption_enabled: bool


class SourceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class SourcesResponse(RootModel[list[SourceItem]]):
    pass


class WantedAlbum(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artist: str
    title: str
    album_id: int
    release_date: str
    album_type: str = ""  # Lidarr albumType: Album / EP / Single
    duration: int = 0  # total album runtime in milliseconds
    track_count: int = 0  # expected track count (Lidarr statistics.trackCount)
    cover_url: str = ""  # album cover art URL (cover-art-archive or Lidarr-local)
    root_folder: str


class WantedResponse(RootModel[list[WantedAlbum]]):
    pass


class AlbumQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artist: str
    title: str
    album_id: int
    root_folder: str = ""


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    albums: list[AlbumQuery]
    sources: list[str] = []


class SearchError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    source_name: str
    message: str


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    source_name: str
    match_url: str
    match_title: str
    match_artists: str
    cover_url: str = ""
    year: int | None = None
    track_count: int | None = None


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artist: str
    title: str
    album_id: int
    root_folder: str
    results: list[MatchResult]
    errors: list[SearchError]


class SearchResponse(RootModel[list[SearchResultItem]]):
    pass


class DownloadItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    artist: str | None = None
    title: str | None = None
    match_url: str | None = None
    album_id: int = 0
    quality: int | str | None = None


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[DownloadItem]
    overrides: dict[str, str] = {}

    @field_validator("overrides")
    @classmethod
    def _validate_overrides(cls, v: dict[str, str]) -> dict[str, str]:
        for key, value in v.items():
            if not _registry.is_session_key(key):
                raise ValueError(
                    f"overrides key {key!r} is not a Tier-3 (scope=session) setting; "
                    "only session-scoped keys are allowed in per-request overrides"
                )
            # Validate the value against the registry too — the resolver returns
            # raw override strings unchanged (no validation at read time), so an
            # invalid value (e.g. ytdlp_format="wma") would otherwise slip past
            # the 202 and surface as an async download failure. Mirror PUT.
            _registry.validate_value(_registry.get(key), str(value))
        return v


class DownloadStartedResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str


class ClaimResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claimed: bool


class SettingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    group: str
    type: str
    scope: str
    secret: bool
    source: str  # "db" | "env" | "default"
    value: str | None = None  # non-secrets only
    is_set: bool = False
    preview: str | None = None  # secrets only — masked
    readonly: bool = False
    file_status: str | None = None  # for ytmusic_oauth_file / ytdlp_cookies_file only


class SettingsResponse(RootModel[list[SettingItem]]):
    pass


class SettingsUpdateRequest(RootModel[dict[str, str]]):
    pass
