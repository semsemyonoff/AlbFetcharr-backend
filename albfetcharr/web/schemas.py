"""Pydantic v2 models for AlbFetcharr API request/response validation."""

from pydantic import BaseModel, ConfigDict, RootModel


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: str


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_quality: int
    default_lang: str
    default_theme: str
    import_enabled: bool


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
    added: str
    status: str
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


class DownloadStartedResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str


class ClaimResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claimed: bool
