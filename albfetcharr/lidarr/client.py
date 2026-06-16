"""Lidarr API client functions."""

import time

import requests


def get_root_folders(base_url: str, api_key: str) -> list[dict]:
    """Fetch all root folders from Lidarr API."""
    resp = requests.get(
        f"{base_url}/api/v1/rootfolder",
        headers={"X-Api-Key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_all_artists(base_url: str, api_key: str) -> list[dict]:
    """Fetch all artists from Lidarr API."""
    resp = requests.get(
        f"{base_url}/api/v1/artist",
        headers={"X-Api-Key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_artist_root_folder(artist_path: str, root_folders: list[dict]) -> str:
    """Determine which root folder an artist belongs to by matching path prefix."""
    artist_path = artist_path.rstrip("/")
    best = ""
    for rf in root_folders:
        rf_path = rf.get("path", "").rstrip("/")
        if artist_path.startswith(rf_path + "/") and len(rf_path) > len(best):
            best = rf_path
    return best


def get_wanted_albums(base_url: str, api_key: str) -> list[dict]:
    """Fetch all wanted/missing albums from Lidarr API."""
    albums = []
    page = 1
    page_size = 50

    while True:
        resp = requests.get(
            f"{base_url}/api/v1/wanted/missing",
            params={
                "page": page,
                "pageSize": page_size,
                "sortKey": "title",
                "sortDirection": "ascending",
            },
            headers={"X-Api-Key": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        records = data.get("records", [])
        if not records:
            break
        albums.extend(records)
        if len(albums) >= data.get("totalRecords", len(albums)):
            break
        page += 1

    return albums


def get_lidarr_track_count(base_url: str, api_key: str, album_id: int) -> int:
    """Get expected track count for an album from Lidarr."""
    resp = requests.get(
        f"{base_url}/api/v1/track",
        params={"albumId": album_id},
        headers={"X-Api-Key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return len(resp.json())


def wait_for_command(base_url: str, api_key: str, command_id: int, timeout: int = 300) -> bool:
    """Wait for a Lidarr command to complete."""
    headers = {"X-Api-Key": api_key}
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{base_url}/api/v1/command/{command_id}", headers=headers, timeout=30
        )
        resp.raise_for_status()
        status = resp.json().get("status", "")
        if status == "completed":
            return True
        if status in ("failed", "aborted"):
            return False
        time.sleep(3)
    return False


def get_album_path(base_url: str, api_key: str, album_id: int) -> str | None:
    """Get album directory path from Lidarr via trackfile paths."""
    from pathlib import Path

    resp = requests.get(
        f"{base_url}/api/v1/trackfile",
        params={"albumId": album_id},
        headers={"X-Api-Key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    files = resp.json()
    if files:
        return str(Path(files[0]["path"]).parent)
    return None
