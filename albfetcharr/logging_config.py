"""Central logging configuration for AlbFetcharr.

A single place that decides the verbosity and format of the application's own
logs. Everything in the package logs through the ``albfetcharr`` logger (module
loggers like ``albfetcharr.lidarr.client`` propagate up to it), so configuring
that one logger controls the whole app.

Verbosity is driven by ``ALBFETCHARR_LOG_LEVEL`` (or the ``app_log_level``
setting, resolved into ``AppConfig.log_level``); ``DEBUG`` turns on the
request/response logging of internal services (Lidarr HTTP calls, yt-dlp, …).
"""

import logging
import os
import sys

LOGGER_NAME = "albfetcharr"
DEFAULT_LEVEL = "INFO"
VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Sentinel attribute marking our handler so configure_logging is idempotent
# (Flask's debug reloader / repeated create_app() calls must not stack handlers).
_HANDLER_TAG = "_albfetcharr_handler"


def _normalize_level(level: str | None) -> int:
    """Map a level name (any case) to a logging constant; fall back to INFO.

    Never raises — an unknown/garbage value degrades to INFO so a misconfigured
    env var can never take the app down at startup.
    """
    if not level:
        return logging.INFO
    value = getattr(logging, level.strip().upper(), None)
    return value if isinstance(value, int) else logging.INFO


def resolve_level_name(level: str | None = None) -> str:
    """Resolve the effective level *name*, honoring the env var when no arg given.

    Precedence: explicit arg → ``ALBFETCHARR_LOG_LEVEL`` env → ``INFO``.
    """
    candidate = level if level is not None else os.environ.get("ALBFETCHARR_LOG_LEVEL")
    return logging.getLevelName(_normalize_level(candidate))


def configure_logging(level: str | None = None) -> str:
    """Configure the ``albfetcharr`` logger; safe to call repeatedly.

    Attaches a single stdout handler the first time, then (re)applies the level
    on every call. Returns the effective level name so callers can log it.

    Args:
        level: Explicit level name (e.g. "DEBUG"). When None, the level comes
            from ``ALBFETCHARR_LOG_LEVEL`` (else INFO).
    """
    effective = _normalize_level(
        level if level is not None else os.environ.get("ALBFETCHARR_LOG_LEVEL")
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(effective)
    # Own the output: emit through our handler only, never the root last-resort
    # handler (which would double-print and ignore our formatter).
    logger.propagate = False

    if not any(getattr(h, _HANDLER_TAG, False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        setattr(handler, _HANDLER_TAG, True)
        logger.addHandler(handler)

    return logging.getLevelName(effective)


def set_level(level: str | None) -> str:
    """Apply a new level to the already-configured logger (live reconfig).

    Used after a settings change so verbosity updates without a restart.
    Returns the effective level name.
    """
    effective = _normalize_level(level)
    logging.getLogger(LOGGER_NAME).setLevel(effective)
    return logging.getLevelName(effective)
