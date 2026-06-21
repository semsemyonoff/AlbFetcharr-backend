"""Pure helpers for computing file-existence status for readonly path settings."""

from __future__ import annotations

import json
import os
from typing import Any


def load_oauth_json(path: str | None) -> dict[str, Any] | None:
    """Load the ytmusic OAuth file as a JSON object.

    Returns the parsed dict, or None when the path is empty/None, the file is
    absent, unreadable, not valid JSON, or valid JSON that is **not** an object
    (e.g. a list or a scalar — ``ytmusicapi`` and our client builder both expect
    a mapping and would otherwise crash on ``.get()``). Shared by
    ``oauth_file_status`` (the UI badge) and the YTMusic client builder so both
    agree on exactly what counts as a usable credentials file.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def oauth_file_status(path: str | None) -> str:
    """Return 'ok', 'missing', or 'invalid' for the ytmusic OAuth file.

    ok      — file exists and parses as a JSON object
    missing — file absent (or path is empty/None)
    invalid — file exists but is not a valid JSON object (malformed, or valid
              JSON that isn't a mapping, e.g. ``[]``)
    """
    if not path:
        return "missing"
    if not os.path.exists(path):
        return "missing"
    return "ok" if load_oauth_json(path) is not None else "invalid"


def cookies_file_status(path: str | None) -> str:
    """Return 'found' or 'missing' for the yt-dlp cookies file.

    found   — file exists at the given path
    missing — file absent (or path is empty/None)
    """
    if not path:
        return "missing"
    return "found" if os.path.exists(path) else "missing"
