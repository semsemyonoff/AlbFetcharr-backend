"""Smoke test for yt-dlp availability."""


def test_ytdlp_import():
    """Verify yt-dlp is installed and importable."""
    import yt_dlp  # noqa: F401


def test_ytdlp_has_version():
    """Verify yt-dlp exposes a version string."""
    import yt_dlp

    assert isinstance(yt_dlp.version.__version__, str)
    assert yt_dlp.version.__version__
