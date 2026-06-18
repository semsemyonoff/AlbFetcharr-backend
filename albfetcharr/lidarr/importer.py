"""Lidarr ManualImport orchestration and post-import cleanup."""

import shutil
from pathlib import Path

import requests

from albfetcharr.download.locator import find_album_dir
from albfetcharr.lidarr.client import get_album_path, wait_for_command
from albfetcharr.lidarr.library_map import resolve_library_path
from albfetcharr.sources.base import LogFn


def run_import(
    base_url: str,
    api_key: str,
    download_path: str,
    *,
    log: LogFn = print,
) -> bool:
    """Run Lidarr ManualImport: scan, build, trigger, and wait for completion.

    Args:
        base_url: Lidarr base URL.
        api_key: Lidarr API key.
        download_path: Lidarr-internal download folder path
            (from ALBFETCHARR_LIDARR_IMPORT_PATH).
        log: Callback for progress messages. Defaults to print.

    Returns:
        True if import completed successfully, False otherwise.
    """
    headers = {"X-Api-Key": api_key}

    log(f"Scanning for import: {download_path}")
    resp = requests.get(
        f"{base_url}/api/v1/manualimport",
        params={"folder": download_path, "filterExistingFiles": "true"},
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    items = resp.json()

    if not items:
        log("  No importable files found by Lidarr.")
        return False

    import_files = []
    for item in items:
        if not item.get("artist") or not item.get("album") or not item.get("tracks"):
            continue
        rejections = item.get("rejections", [])
        if rejections:
            reasons = ", ".join(r.get("reason", "") for r in rejections)
            log(f"  Skipping {item['path']}: {reasons}")
            continue
        album_release = item.get("albumReleaseId", 0)
        if not album_release and item.get("album", {}).get("releases"):
            for release in item["album"]["releases"]:
                if release.get("monitored"):
                    album_release = release["id"]
                    break
            if not album_release:
                album_release = item["album"]["releases"][0]["id"]
        if not album_release:
            log(f"  Skipping {item['path']}: no album release found")
            continue
        import_files.append(
            {
                "path": item["path"],
                "artistId": item["artist"]["id"],
                "albumId": item["album"]["id"],
                "albumReleaseId": album_release,
                "trackIds": [t["id"] for t in item["tracks"]],
                "quality": item["quality"],
                "releaseGroup": item.get("releaseGroup", ""),
                "indexerFlags": item.get("indexerFlags", 0),
                "additionalFile": item.get("additionalFile", False),
                "replaceExistingFiles": True,
                "disableReleaseSwitching": False,
            }
        )

    if not import_files:
        log(f"  Lidarr found {len(items)} file(s) but none matched an artist/album.")
        return False

    log(f"  Importing {len(import_files)} file(s) into Lidarr...")
    resp = requests.post(
        f"{base_url}/api/v1/command",
        json={
            "name": "ManualImport",
            "files": import_files,
            "importMode": "move",
        },
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    command_id = resp.json().get("id")
    log("  Lidarr import triggered, waiting for completion...")

    if command_id is not None and wait_for_command(base_url, api_key, command_id):
        log("  Import completed.")
        return True
    else:
        log("  Import did not complete successfully.")
        return False


def post_import_cleanup(
    download_dir: str,
    base_url: str,
    api_key: str,
    albums: list[dict],
    *,
    library_map: dict[str, str] | None = None,
    log: LogFn = print,
) -> None:
    """Move cover art to library and clean up empty download directories.

    Args:
        download_dir: Local path to the download directory (where albums are downloaded).
        base_url: Lidarr base URL.
        api_key: Lidarr API key.
        albums: List of dicts with 'artist', 'title', 'album_id' keys (from ready_for_import).
        library_map: Parsed library path mapping; when None, library paths are used as-is.
        log: Callback for progress messages. Defaults to print.
    """
    for album_info in albums:
        try:
            artist = album_info["artist"]
            title = album_info["title"]
            album_id = album_info["album_id"]

            album_dir = find_album_dir(download_dir, artist, title)
            if album_dir is None:
                continue

            cover_src = None
            for _ext in (".jpg", ".jpeg", ".webp", ".png"):
                candidate = album_dir / f"cover{_ext}"
                if candidate.exists():
                    cover_src = candidate
                    break
            if cover_src is None:
                for _f in album_dir.iterdir():
                    if _f.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png"):
                        cover_src = _f
                        break
            if cover_src is not None:
                dest_path = get_album_path(base_url, api_key, album_id)
                if not dest_path:
                    log(
                        f"  WARNING: library path not found for album {album_id},"
                        " cover art will be discarded"
                    )
                if dest_path:
                    dest_path = resolve_library_path(dest_path, library_map)
                    dest_dir = Path(dest_path)
                    if not dest_dir.exists():
                        log(
                            f"  WARNING: Library path not accessible: {dest_path},"
                            " cover art will be discarded"
                        )
                    else:
                        cover_dst = dest_dir / f"cover{cover_src.suffix.lower()}"
                        if not cover_dst.exists():
                            log(f"  Moving cover: {album_dir.name} -> {dest_path}")
                            shutil.move(str(cover_src), str(cover_dst))

            if album_dir.exists():
                shutil.rmtree(album_dir)
                log(f"  Removed download dir: {album_dir}")

            artist_dir = album_dir.parent
            if artist_dir.exists() and not any(artist_dir.iterdir()):
                artist_dir.rmdir()
                log(f"  Removed empty artist dir: {artist_dir}")
        except Exception as e:
            log(f"  WARNING: cleanup failed for {album_info.get('title', '?')}: {e}")
