"""Pure helpers for computing file-existence status for readonly path settings."""

from __future__ import annotations

import json
import os


def oauth_file_status(path: str | None) -> str:
    """Return 'ok', 'missing', or 'invalid' for the ytmusic OAuth file.

    ok      — file exists and parses as JSON
    missing — file absent (or path is empty/None)
    invalid — file exists but is not valid JSON
    """
    if not path:
        return "missing"
    if not os.path.exists(path):
        return "missing"
    try:
        with open(path, encoding="utf-8") as fh:
            json.load(fh)
        return "ok"
    except (OSError, ValueError):
        return "invalid"


def cookies_file_status(path: str | None) -> str:
    """Return 'found' or 'missing' for the yt-dlp cookies file.

    found   — file exists at the given path
    missing — file absent (or path is empty/None)
    """
    if not path:
        return "missing"
    return "found" if os.path.exists(path) else "missing"
