"""Tests for config loading."""

import os
from unittest.mock import patch

from albfetcharr.config import (
    UIDefaults,
    YtDlpOptions,
    load_app_config,
    load_ui_defaults,
    load_yandex_options,
    load_ytdlp_options,
)


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

    def test_ytmusic_client_id_from_env(self):
        """ALBFETCHARR_YTMUSIC_CLIENT_ID is read into ytmusic_client_id."""
        with patch.dict(os.environ, {"ALBFETCHARR_YTMUSIC_CLIENT_ID": "my-client-id"}, clear=False):
            assert load_ytdlp_options().ytmusic_client_id == "my-client-id"

    def test_ytmusic_client_secret_from_env(self):
        """ALBFETCHARR_YTMUSIC_CLIENT_SECRET is read into ytmusic_client_secret."""
        with patch.dict(
            os.environ, {"ALBFETCHARR_YTMUSIC_CLIENT_SECRET": "my-secret"}, clear=False
        ):
            assert load_ytdlp_options().ytmusic_client_secret == "my-secret"

    def test_ytmusic_client_id_absent_is_none(self):
        """Unset ALBFETCHARR_YTMUSIC_CLIENT_ID leaves ytmusic_client_id None."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_YTMUSIC_CLIENT_ID"}
        with patch.dict(os.environ, env, clear=True):
            assert load_ytdlp_options().ytmusic_client_id is None

    def test_ytmusic_client_secret_absent_is_none(self):
        """Unset ALBFETCHARR_YTMUSIC_CLIENT_SECRET leaves ytmusic_client_secret None."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_YTMUSIC_CLIENT_SECRET"}
        with patch.dict(os.environ, env, clear=True):
            assert load_ytdlp_options().ytmusic_client_secret is None

    def test_ytmusic_client_id_empty_coalesces_to_none(self):
        """Empty string ALBFETCHARR_YTMUSIC_CLIENT_ID coalesces to None."""
        with patch.dict(os.environ, {"ALBFETCHARR_YTMUSIC_CLIENT_ID": ""}, clear=False):
            assert load_ytdlp_options().ytmusic_client_id is None

    def test_path_pattern_from_env(self):
        """ALBFETCHARR_YTDLP_PATH_PATTERN overrides the default yt-dlp output template."""
        custom = "%(album)s/%(title)s.%(ext)s"
        with patch.dict(os.environ, {"ALBFETCHARR_YTDLP_PATH_PATTERN": custom}, clear=False):
            assert load_ytdlp_options().path_pattern == custom

    def test_path_pattern_default(self):
        """path_pattern defaults to the %(artist)s/... template when env is unset."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_YTDLP_PATH_PATTERN"}
        with patch.dict(os.environ, env, clear=True):
            opts = load_ytdlp_options()
            assert "%(artist)s" in opts.path_pattern
            assert "%(ext)s" in opts.path_pattern

    def test_path_pattern_empty_env_uses_default(self):
        """An empty ALBFETCHARR_YTDLP_PATH_PATTERN coalesces to the default template."""
        with patch.dict(os.environ, {"ALBFETCHARR_YTDLP_PATH_PATTERN": ""}, clear=False):
            assert "%(artist)s" in load_ytdlp_options().path_pattern

    def test_ytdlp_options_is_ytdlp_options_instance(self):
        """load_ytdlp_options returns a YtDlpOptions instance."""
        assert isinstance(load_ytdlp_options(), YtDlpOptions)


class TestLoadYandexOptions:
    """Tests for load_yandex_options() — focused on renamed env vars."""

    def test_yandex_path_pattern_new_env(self):
        """ALBFETCHARR_YANDEX_PATH_PATTERN sets the Yandex path pattern."""
        with patch.dict(
            os.environ, {"ALBFETCHARR_YANDEX_PATH_PATTERN": "#artist/#album"}, clear=False
        ):
            assert load_yandex_options().path_pattern == "#artist/#album"

    def test_yandex_path_pattern_absent_is_none(self):
        """Absent ALBFETCHARR_YANDEX_PATH_PATTERN leaves path_pattern None (tool default)."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_YANDEX_PATH_PATTERN"}
        with patch.dict(os.environ, env, clear=True):
            assert load_yandex_options().path_pattern is None

    def test_yandex_path_pattern_old_env_ignored(self):
        """Old ALBFETCHARR_PATH_PATTERN is no longer read (renamed)."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ALBFETCHARR_PATH_PATTERN", "ALBFETCHARR_YANDEX_PATH_PATTERN")
        }
        env["ALBFETCHARR_PATH_PATTERN"] = "#old-pattern"
        with patch.dict(os.environ, env, clear=True):
            assert load_yandex_options().path_pattern is None

    def test_yandex_timeout_renamed_env(self):
        """ALBFETCHARR_YANDEX_TIMEOUT is read (renamed from ALBFETCHARR_TIMEOUT)."""
        with patch.dict(os.environ, {"ALBFETCHARR_YANDEX_TIMEOUT": "30"}, clear=False):
            assert load_yandex_options().timeout == "30"

    def test_yandex_tries_renamed_env(self):
        """ALBFETCHARR_YANDEX_TRIES is read (renamed from ALBFETCHARR_TRIES)."""
        with patch.dict(os.environ, {"ALBFETCHARR_YANDEX_TRIES": "10"}, clear=False):
            assert load_yandex_options().tries == "10"

    def test_yandex_retry_delay_renamed_env(self):
        """ALBFETCHARR_YANDEX_RETRY_DELAY is read (renamed from ALBFETCHARR_RETRY_DELAY)."""
        with patch.dict(os.environ, {"ALBFETCHARR_YANDEX_RETRY_DELAY": "3"}, clear=False):
            assert load_yandex_options().retry_delay == "3"

    def test_yandex_old_timeout_ignored(self):
        """Old ALBFETCHARR_TIMEOUT is no longer read (renamed)."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ALBFETCHARR_TIMEOUT", "ALBFETCHARR_YANDEX_TIMEOUT")
        }
        env["ALBFETCHARR_TIMEOUT"] = "99"
        with patch.dict(os.environ, env, clear=True):
            assert load_yandex_options().timeout == "20"  # default


class TestLoadAppConfig:
    """Tests for load_app_config() — focused on enable_* toggles."""

    def test_enable_yandex_default_true(self):
        """enable_yandex defaults to True when env is unset."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_ENABLE_YANDEX"}
        with patch.dict(os.environ, env, clear=True):
            assert load_app_config().enable_yandex is True

    def test_enable_youtube_music_default_true(self):
        """enable_youtube_music defaults to True when env is unset."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_ENABLE_YOUTUBE_MUSIC"}
        with patch.dict(os.environ, env, clear=True):
            assert load_app_config().enable_youtube_music is True

    def test_enable_soundcloud_default_true(self):
        """enable_soundcloud defaults to True when env is unset."""
        env = {k: v for k, v in os.environ.items() if k != "ALBFETCHARR_ENABLE_SOUNDCLOUD"}
        with patch.dict(os.environ, env, clear=True):
            assert load_app_config().enable_soundcloud is True

    def test_enable_yandex_zero_is_false(self):
        """ALBFETCHARR_ENABLE_YANDEX=0 disables Yandex."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_YANDEX": "0"}, clear=False):
            assert load_app_config().enable_yandex is False

    def test_enable_youtube_music_zero_is_false(self):
        """ALBFETCHARR_ENABLE_YOUTUBE_MUSIC=0 disables YouTube Music."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_YOUTUBE_MUSIC": "0"}, clear=False):
            assert load_app_config().enable_youtube_music is False

    def test_enable_soundcloud_zero_is_false(self):
        """ALBFETCHARR_ENABLE_SOUNDCLOUD=0 disables SoundCloud."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_SOUNDCLOUD": "0"}, clear=False):
            assert load_app_config().enable_soundcloud is False

    def test_enable_yandex_false_string_is_false(self):
        """ALBFETCHARR_ENABLE_YANDEX=false disables Yandex (intentional semantics tightening)."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_YANDEX": "false"}, clear=False):
            assert load_app_config().enable_yandex is False

    def test_enable_youtube_music_false_string_is_false(self):
        """ALBFETCHARR_ENABLE_YOUTUBE_MUSIC=false disables YouTube Music."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_YOUTUBE_MUSIC": "false"}, clear=False):
            assert load_app_config().enable_youtube_music is False

    def test_enable_soundcloud_no_string_is_false(self):
        """ALBFETCHARR_ENABLE_SOUNDCLOUD=no disables SoundCloud."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_SOUNDCLOUD": "no"}, clear=False):
            assert load_app_config().enable_soundcloud is False

    def test_enable_yandex_true_string_is_true(self):
        """ALBFETCHARR_ENABLE_YANDEX=true enables Yandex."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_YANDEX": "true"}, clear=False):
            assert load_app_config().enable_yandex is True

    def test_enable_youtube_music_yes_string_is_true(self):
        """ALBFETCHARR_ENABLE_YOUTUBE_MUSIC=yes enables YouTube Music."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_YOUTUBE_MUSIC": "yes"}, clear=False):
            assert load_app_config().enable_youtube_music is True

    def test_enable_soundcloud_one_string_is_true(self):
        """ALBFETCHARR_ENABLE_SOUNDCLOUD=1 enables SoundCloud."""
        with patch.dict(os.environ, {"ALBFETCHARR_ENABLE_SOUNDCLOUD": "1"}, clear=False):
            assert load_app_config().enable_soundcloud is True
