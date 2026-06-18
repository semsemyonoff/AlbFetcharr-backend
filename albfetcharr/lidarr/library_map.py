"""Library path mapping between Lidarr and albfetcharr mount points."""

import logging

logger = logging.getLogger("albfetcharr")


def parse_library_map_str(raw: str | None) -> dict[str, str]:
    """Parse a library map string into a path mapping dict.

    Format: lidarr_path=albfetcharr_path,lidarr_path2=albfetcharr_path2
    Maps Lidarr-internal root folder paths to albfetcharr mount points.
    """
    if not raw:
        return {}
    mapping = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        lidarr_path, albfetcharr_path = pair.split("=", 1)
        mapping[lidarr_path.rstrip("/")] = albfetcharr_path.rstrip("/")
    return mapping


def resolve_library_path(lidarr_path: str, mapping: dict[str, str] | None = None) -> str:
    """Convert a Lidarr-internal path to an albfetcharr-accessible path.

    Uses the provided mapping dict; returns the original path when no mapping is given.
    Finds the longest matching prefix in the mapping and substitutes it.
    Returns the original path if no mapping is configured or no prefix matches.
    """
    if not mapping:
        return lidarr_path

    best_prefix = ""
    best_replacement = ""
    for lidarr_prefix, albfetcharr_prefix in mapping.items():
        if (lidarr_path.startswith(lidarr_prefix + "/") or lidarr_path == lidarr_prefix) and len(
            lidarr_prefix
        ) > len(best_prefix):
            best_prefix = lidarr_prefix
            best_replacement = albfetcharr_prefix

    if best_prefix:
        return best_replacement + lidarr_path[len(best_prefix) :]
    return lidarr_path


def validate_library_map(root_folders: list[dict], mapping: dict[str, str] | None = None) -> None:
    """Check that all Lidarr root folders have a corresponding mapping entry.

    Args:
        root_folders: list of root folder dicts (with 'path' key) from Lidarr API
        mapping: parsed mapping dict; when None or empty, validation is skipped
    """
    if not mapping:
        return

    for rf in root_folders:
        rf_path = rf.get("path", "").rstrip("/")
        if not rf_path:
            continue
        # Use same prefix-match logic as resolve_library_path so a root folder
        # that is a subdirectory of a mapped prefix doesn't produce a spurious warning.
        covered = any(rf_path.startswith(prefix + "/") or rf_path == prefix for prefix in mapping)
        if not covered:
            logger.warning("root folder %r not in ALBFETCHARR_LIBRARY_MAP", rf_path)
