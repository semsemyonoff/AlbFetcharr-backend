"""Tests for config loading."""

import os
from unittest.mock import patch

from albfetcharr.config import UIDefaults, load_ui_defaults, load_ytdlp_options


class TestLoadUIDefaults:
    """Tests for load_ui_defaults()."""

    def test_load_ui_defaults_with_valid_env_vars(self):
        """Test loading with valid ALBFETCHARR_DEFAULT_LANG and ALBFETCHARR_DEFAULT_THEME."""
        with patch.dict(
            os.environ,
            {
                "ALBFETCHARR_DEFAULT_LANG": "ru",
                "ALBFETCHARR_DEFAULT_THEME": "dark",
            },
            clear=False,
        ):
            result = load_ui_defaults()
            assert result.language == "ru"
            assert result.theme == "dark"

    def test_load_ui_defaults_with_defaults(self):
        """Test loading with env vars unset defaults to en/system."""
        with patch.dict(
            os.environ,
            {"ALBFETCHARR_DEFAULT_LANG": "", "ALBFETCHARR_DEFAULT_THEME": ""},
            clear=False,
        ):
            # Delete these keys if they exist
            for key in ["ALBFETCHARR_DEFAULT_LANG", "ALBFETCHARR_DEFAULT_THEME"]:
                if key in os.environ:
                    del os.environ[key]
            result = load_ui_defaults()
            assert result.language == "en"
            assert result.theme == "system"

    def test_load_ui_defaults_invalid_language(self, caplog):
        """Test invalid language falls back to en with warning."""
        with patch.dict(
            os.environ,
            {"ALBFETCHARR_DEFAULT_LANG": "fr"},
            clear=False,
        ):
            result = load_ui_defaults()
            assert result.language == "en"
            assert "Invalid ALBFETCHARR_DEFAULT_LANG" in caplog.text

    def test_load_ui_defaults_invalid_theme(self, caplog):
        """Test invalid theme falls back to system with warning."""
        with patch.dict(
            os.environ,
            {"ALBFETCHARR_DEFAULT_THEME": "neon"},
            clear=False,
        ):
            result = load_ui_defaults()
            assert result.theme == "system"
            assert "Invalid ALBFETCHARR_DEFAULT_THEME" in caplog.text

    def test_load_ui_defaults_returns_ui_defaults_instance(self):
        """Test that load_ui_defaults returns a UIDefaults instance."""
        result = load_ui_defaults()
        assert isinstance(result, UIDefaults)
        assert hasattr(result, "language")
        assert hasattr(result, "theme")


class TestLoadYtDlpOptions:
    """Tests for load_ytdlp_options() — focused on the cookies_file env wiring."""

    def test_cookies_file_set_from_env(self):
        """ALBFETCHARR_YTDLP_COOKIES is read into cookies_file."""
        with patch.dict(
            os.environ,
            {"ALBFETCHARR_YTDLP_COOKIES": "/hub/cookies.txt"},
            clear=False,
        ):
            assert load_ytdlp_options().cookies_file == "/hub/cookies.txt"

    def test_cookies_file_empty_env_coalesces_to_none(self):
        """An empty-string env var becomes None (no cookiefile is later added)."""
        with patch.dict(
            os.environ,
            {"ALBFETCHARR_YTDLP_COOKIES": ""},
            clear=False,
        ):
            assert load_ytdlp_options().cookies_file is None

    def test_cookies_file_absent_is_none(self):
        """An unset env var leaves cookies_file None."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALBFETCHARR_YTDLP_COOKIES", None)
            assert load_ytdlp_options().cookies_file is None
