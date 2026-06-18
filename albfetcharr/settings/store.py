"""SQLite-backed settings store.

Opens a fresh connection per call (commit-and-close) — the table is tiny and
low-frequency under gunicorn's 1-worker/4-threads model, so per-call connections
avoid any shared-connection locking complexity.

DB path defaults to /config/albfetcharr.db and is overridden by
ALBFETCHARR_DB_PATH.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

_DEFAULT_DB_PATH = "/config/albfetcharr.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    is_secret  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


def _db_path() -> str:
    return os.environ.get("ALBFETCHARR_DB_PATH", _DEFAULT_DB_PATH)


def _connect(path: str) -> sqlite3.Connection:
    # Ensure the parent directory exists — sqlite3.connect creates the DB file
    # but not its directory, so a missing /config mount would otherwise raise
    # OperationalError on the first read/write. Skip for ":memory:" / bare names.
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_raw(key: str, *, db_path: str | None = None) -> tuple[str, bool] | None:
    """Return (value, is_secret) for key, or None if absent."""
    path = db_path or _db_path()
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT value, is_secret FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return row["value"], bool(row["is_secret"])


def set_raw(key: str, value: str, *, is_secret: bool = False, db_path: str | None = None) -> None:
    """Upsert key=value; stamps updated_at to current UTC time."""
    path = db_path or _db_path()
    now = _now_utc()
    with closing(_connect(path)) as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, is_secret, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                is_secret  = excluded.is_secret,
                updated_at = excluded.updated_at
            """,
            (key, value, int(is_secret), now),
        )
        conn.commit()


def delete(key: str, *, db_path: str | None = None) -> bool:
    """Delete key. Returns True if a row was removed, False if key was absent."""
    path = db_path or _db_path()
    with closing(_connect(path)) as conn:
        cursor = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()
    return cursor.rowcount > 0


def all_raw(*, db_path: str | None = None) -> dict[str, tuple[str, bool]]:
    """Return {key: (value, is_secret)} for all stored settings."""
    path = db_path or _db_path()
    with closing(_connect(path)) as conn:
        rows = conn.execute("SELECT key, value, is_secret FROM settings").fetchall()
    return {row["key"]: (row["value"], bool(row["is_secret"])) for row in rows}
