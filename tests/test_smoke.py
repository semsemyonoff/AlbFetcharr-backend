from importlib.metadata import version

from albfetcharr import __version__


def test_import():
    # __version__ is sourced from the installed package metadata (pyproject),
    # not a hardcoded literal — so it always matches the distribution version.
    assert __version__ == version("albfetcharr")
