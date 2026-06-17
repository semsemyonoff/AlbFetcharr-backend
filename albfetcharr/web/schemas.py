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
