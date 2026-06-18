"""Service and bundled-tool version reporting.

Single source of truth for the version: the installed package metadata
(``pyproject [project].version``, read via ``importlib.metadata``), re-exported
as ``albfetcharr.__version__``. ``APP_VERSION`` is the version the service
*reports* (OpenAPI ``info.version`` — see ``albfetcharr.web.spec`` — and ``GET
/api/version``): in the production image a build-time ``APP_VERSION`` env
override is baked in (wired from the release tag by the deploy repo's build
script); otherwise it falls back to the package version. The bundled yt-dlp /
yandex-music-downloader versions come from the same metadata mechanism.
"""

import importlib.metadata
import os


def _dist_version(distribution: str) -> str:
    """Installed version of ``distribution``, or ``"unknown"`` if not present."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


#: Installed package version — the single source of truth (pyproject version).
__version__ = _dist_version("albfetcharr")

#: Version the service reports; a build-time ``APP_VERSION`` env override falls
#: back to the installed package version.
APP_VERSION = os.environ.get("APP_VERSION") or __version__


def get_versions() -> dict[str, str]:
    """Service version plus the bundled yt-dlp / yandex-music-downloader versions.

    ``albfetcharr`` is :data:`APP_VERSION`; the tool versions are read live from
    installed package metadata so they always reflect what would actually run.
    """
    return {
        "albfetcharr": APP_VERSION,
        "yt_dlp": _dist_version("yt-dlp"),
        "ymd": _dist_version("yandex-music-downloader"),
    }
