"""Tests for albfetcharr.logging_config."""

import logging

import pytest

from albfetcharr import logging_config
from albfetcharr.logging_config import (
    LOGGER_NAME,
    configure_logging,
    resolve_level_name,
    set_level,
)


@pytest.fixture(autouse=True)
def _restore_logger():
    """Snapshot and restore the albfetcharr logger so these tests don't leak
    handlers / propagate / level state into the rest of the suite."""
    logger = logging.getLogger(LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    logger.handlers = []
    try:
        yield
    finally:
        logger.handlers, logger.level, logger.propagate = (saved[0], saved[1], saved[2])


class TestConfigureLogging:
    def test_default_level_is_info(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        assert configure_logging() == "INFO"
        assert logging.getLogger(LOGGER_NAME).level == logging.INFO

    def test_explicit_level_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_LOG_LEVEL", "WARNING")
        assert configure_logging("DEBUG") == "DEBUG"
        assert logging.getLogger(LOGGER_NAME).level == logging.DEBUG

    def test_level_from_env(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_LOG_LEVEL", "ERROR")
        assert configure_logging() == "ERROR"

    def test_garbage_level_degrades_to_info(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        assert configure_logging("NONSENSE") == "INFO"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        assert configure_logging("debug") == "DEBUG"

    def test_attaches_handler_writing_to_stdout(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        configure_logging()
        logger = logging.getLogger(LOGGER_NAME)
        tagged = [h for h in logger.handlers if getattr(h, "_albfetcharr_handler", False)]
        assert len(tagged) == 1

    def test_idempotent_no_duplicate_handlers(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        configure_logging()
        configure_logging()
        configure_logging("DEBUG")
        logger = logging.getLogger(LOGGER_NAME)
        tagged = [h for h in logger.handlers if getattr(h, "_albfetcharr_handler", False)]
        assert len(tagged) == 1

    def test_does_not_propagate_to_root(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        configure_logging()
        assert logging.getLogger(LOGGER_NAME).propagate is False


class TestSetLevel:
    def test_set_level_updates_effective_level(self):
        configure_logging("INFO")
        assert set_level("DEBUG") == "DEBUG"
        assert logging.getLogger(LOGGER_NAME).level == logging.DEBUG

    def test_set_level_garbage_degrades_to_info(self):
        configure_logging("DEBUG")
        assert set_level("???") == "INFO"


class TestResolveLevelName:
    def test_explicit_arg(self):
        assert resolve_level_name("warning") == "WARNING"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_LOG_LEVEL", "DEBUG")
        assert resolve_level_name() == "DEBUG"

    def test_default(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_LOG_LEVEL", raising=False)
        assert resolve_level_name() == "INFO"


def test_valid_levels_constant_matches_normalizer():
    """Every advertised level must map to a real logging constant."""
    for name in logging_config.VALID_LEVELS:
        assert isinstance(getattr(logging, name), int)
