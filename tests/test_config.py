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

    def test_download_retries_default(self):
        """download_retries defaults to 3 when the env var is unset."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALBFETCHARR_YTDLP_RETRIES", None)
            assert load_ytdlp_options().download_retries == 3

    def test_download_retries_from_env(self):
        """ALBFETCHARR_YTDLP_RETRIES is parsed into download_retries."""
        with patch.dict(os.environ, {"ALBFETCHARR_YTDLP_RETRIES": "5"}, clear=False):
            assert load_ytdlp_options().download_retries == 5

    def test_download_retries_clamped_to_at_least_one(self):
        """A zero/negative or invalid value clamps to a single attempt (no retry)."""
        with patch.dict(os.environ, {"ALBFETCHARR_YTDLP_RETRIES": "0"}, clear=False):
            assert load_ytdlp_options().download_retries == 1
        with patch.dict(os.environ, {"ALBFETCHARR_YTDLP_RETRIES": "nan"}, clear=False):
            # invalid -> default 3 (max(1, 3))
            assert load_ytdlp_options().download_retries == 3

    def test_ytmusic_oauth_file_default(self):
        """ytmusic_oauth_file defaults to the canonical /config path when unset."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALBFETCHARR_YTMUSIC_OAUTH", None)
            assert load_ytdlp_options().ytmusic_oauth_file == "/config/ytmusic_oauth.json"

    def test_ytmusic_oauth_file_from_env(self):
        """ALBFETCHARR_YTMUSIC_OAUTH overrides the oauth file path."""
        with patch.dict(
            os.environ, {"ALBFETCHARR_YTMUSIC_OAUTH": "/config/custom.json"}, clear=False
        ):
            assert load_ytdlp_options().ytmusic_oauth_file == "/config/custom.json"

    def test_ytmusic_oauth_file_empty_env_uses_default(self):
        """An empty env var coalesces back to the default path (compose passes blank)."""
        with patch.dict(os.environ, {"ALBFETCHARR_YTMUSIC_OAUTH": ""}, clear=False):
            assert load_ytdlp_options().ytmusic_oauth_file == "/config/ytmusic_oauth.json"
