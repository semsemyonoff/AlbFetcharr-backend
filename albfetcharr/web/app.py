"""Flask application factory for AlbFetcharr."""

import logging

from flask import Flask

from albfetcharr.lidarr.client import get_root_folders
from albfetcharr.lidarr.library_map import parse_library_map_str, validate_library_map
from albfetcharr.logging_config import configure_logging, set_level
from albfetcharr.settings.resolver import resolve_app_config
from albfetcharr.sources import bootstrap_default_providers
from albfetcharr.web.routes import register_routes
from albfetcharr.web.spec import api

logger = logging.getLogger("albfetcharr")


def create_app() -> Flask:
    """Create and configure the Flask application."""
    # Bring up logging first (from ALBFETCHARR_LOG_LEVEL) so startup is captured.
    configure_logging()

    app = Flask(__name__, static_folder="static")

    register_routes(app)
    api.register(app)

    bootstrap_default_providers()

    try:
        cfg = resolve_app_config()
        # A DB-stored log level (app_log_level) overrides the env bootstrap.
        set_level(cfg.log_level)
        logger.info("Logging configured at level %s", cfg.log_level)
        lidarr = cfg.lidarr
        if lidarr.base_url and lidarr.api_key:
            root_folders = get_root_folders(lidarr.base_url, lidarr.api_key)
            validate_library_map(root_folders, parse_library_map_str(lidarr.library_map))
    except Exception:
        logger.warning("Could not validate library map against Lidarr (is Lidarr available?)")

    return app
