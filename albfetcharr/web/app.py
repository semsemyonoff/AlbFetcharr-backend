"""Flask application factory for AlbFetcharr."""

import logging

from flask import Flask

from albfetcharr.config import load_lidarr_config
from albfetcharr.lidarr.client import get_root_folders
from albfetcharr.lidarr.library_map import validate_library_map
from albfetcharr.sources import bootstrap_default_providers
from albfetcharr.web.routes import register_routes

logger = logging.getLogger("albfetcharr")


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder="static")

    register_routes(app)

    bootstrap_default_providers()

    try:
        cfg = load_lidarr_config()
        if cfg.base_url and cfg.api_key:
            root_folders = get_root_folders(cfg.base_url, cfg.api_key)
            validate_library_map(root_folders)
    except Exception:
        logger.warning(
            "Could not validate library map against Lidarr (is Lidarr available?)"
        )

    return app
