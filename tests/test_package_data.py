"""Tests to verify package data is included in editable installs."""

from importlib.resources import files


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
