"""Lidarr API client functions.

All outbound HTTP to Lidarr goes through ``_request``, which logs the request
(method/URL/params/body) and the response (status/elapsed/size, plus the body
at DEBUG). The ``X-Api-Key`` header is never logged. Successful calls log at
DEBUG (so ``ALBFETCHARR_LOG_LEVEL=DEBUG`` surfaces the full conversation with
Lidarr); failures (status >= 400 or transport errors) log at WARNING so they
stay visible at the default level.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Cap on how much of a request/response body we put in the logs, so a large
# wanted-albums payload can't flood the log. The full size is always reported.
_MAX_BODY_LOG = 4000


def _truncate(text: object, limit: int = _MAX_BODY_LOG) -> str:
    """Stringify and clip `text` for logging, noting the original length."""
    s = text if isinstance(text, str) else str(text)
    if len(s) <= limit:
        return s
    return f"{s[:limit]}… ({len(s)} chars total)"


def _request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    json: dict | None = None,
    timeout: int = 30,
) -> requests.Response:
    """Perform a logged HTTP request to Lidarr and return the response.

    Does NOT call ``raise_for_status`` — callers keep that responsibility, so
    error responses are logged here (at WARNING) and then surfaced by the caller.
    """
    if logger.isEnabledFor(logging.DEBUG):
        detail = []
        if params:
            detail.append(f"params={params}")
        if json is not None:
            detail.append(f"body={_truncate(json)}")
        logger.debug("request: %s %s %s", method, url, " ".join(detail))

    started = time.monotonic()
    try:
        resp = requests.request(
            method, url, headers=headers, params=params, json=json, timeout=timeout
        )
    except requests.RequestException as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.warning("request failed: %s %s after %.0f ms: %s", method, url, elapsed_ms, exc)
        raise

    elapsed_ms = (time.monotonic() - started) * 1000
    size = len(resp.content or b"")
    if resp.status_code >= 400:
        logger.warning(
            "response: %s %s %s (%.0f ms, %d B): %s",
            resp.status_code,
            method,
            url,
            elapsed_ms,
            size,
            _truncate(resp.text, 500),
        )
    else:
        logger.debug(
            "response: %s %s %s (%.0f ms, %d B)", resp.status_code, method, url, elapsed_ms, size
        )
        if size and logger.isEnabledFor(logging.DEBUG):
            logger.debug("response body: %s", _truncate(resp.text))
    return resp


def get_root_folders(base_url: str, api_key: str) -> list[dict]:
    """Fetch all root folders from Lidarr API."""
    resp = _request(
        "GET",
        f"{base_url}/api/v1/rootfolder",
        headers={"X-Api-Key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_all_artists(base_url: str, api_key: str) -> list[dict]:
    """Fetch all artists from Lidarr API."""
    resp = _request(
        "GET",
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
        resp = _request(
            "GET",
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
    resp = _request(
        "GET",
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
        resp = _request(
            "GET", f"{base_url}/api/v1/command/{command_id}", headers=headers, timeout=30
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

    resp = _request(
        "GET",
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
