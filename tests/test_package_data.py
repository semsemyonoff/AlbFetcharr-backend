"""Tests to verify package data is included in editable installs."""

from importlib.resources import files
from pathlib import Path

import pytest


def test_static_dist_is_package_data_when_built():
    """Verify static/dist/index.html is accessible via importlib.resources when built."""
    p = files("albfetcharr.web")
    dist_path = p / "static" / "dist" / "index.html"

    # If the frontend has been built, the file should exist
    if dist_path.is_file():
        # Verify it's not empty and looks like HTML
        content = dist_path.read_text()
        assert len(content) > 0, "static/dist/index.html is empty"
        looks_like_html = "<!DOCTYPE html>" in content or "<html" in content
        assert looks_like_html, "static/dist/index.html doesn't look like HTML"
    else:
        # Frontend not built is okay in some contexts (e.g., CI without build step)
        # but we expect it in a normal dev environment
        # Check if we're in the source tree where npm run build should have been run
        src_dist = (
            Path(__file__).parent.parent / "albfetcharr" / "web" / "static" / "dist" / "index.html"
        )
        if not src_dist.exists():
            pytest.skip(
                "Frontend not built — build the frontend repo and deploy dist into static/dist"
            )


def test_logo_svg_exists():
    """Verify static/logo/AlbFetcharr.svg is accessible via importlib.resources."""
    p = files("albfetcharr.web")
    assert (p / "static" / "logo" / "AlbFetcharr.svg").is_file()


def test_logo_png_32_exists():
    """Verify static/logo/AlbFetcharr-32.png is accessible."""
    p = files("albfetcharr.web")
    assert (p / "static" / "logo" / "AlbFetcharr-32.png").is_file()


def test_logo_png_64_exists():
    """Verify static/logo/AlbFetcharr-64.png is accessible."""
    p = files("albfetcharr.web")
    assert (p / "static" / "logo" / "AlbFetcharr-64.png").is_file()


def test_logo_png_128_exists():
    """Verify static/logo/AlbFetcharr-128.png is accessible."""
    p = files("albfetcharr.web")
    assert (p / "static" / "logo" / "AlbFetcharr-128.png").is_file()


def test_logo_png_512_exists():
    """Verify static/logo/AlbFetcharr-512.png is accessible."""
    p = files("albfetcharr.web")
    assert (p / "static" / "logo" / "AlbFetcharr-512.png").is_file()
