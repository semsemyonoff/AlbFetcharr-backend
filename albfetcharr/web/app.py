"""Flask application factory for AlbFetcharr."""

import logging

from flask import Flask

from albfetcharr.lidarr.client import get_root_folders
from albfetcharr.lidarr.library_map import validate_library_map
from albfetcharr.settings.resolver import resolve_app_config
from albfetcharr.sources import bootstrap_default_providers
from albfetcharr.web.routes import register_routes
from albfetcharr.web.spec import api

logger = logging.getLogger("albfetcharr")


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder="static")

    register_routes(app)
    api.register(app)

    bootstrap_default_providers()

    try:
        lidarr = resolve_app_config().lidarr
        if lidarr.base_url and lidarr.api_key:
            root_folders = get_root_folders(lidarr.base_url, lidarr.api_key)
            validate_library_map(root_folders)
    except Exception:
        logger.warning("Could not validate library map against Lidarr (is Lidarr available?)")

    return app
