"""Tests for albfetcharr.settings.registry."""

import pytest

from albfetcharr.settings import registry
from albfetcharr.settings.registry import Setting, validate_value


class TestCatalogIntegrity:
    """Structural invariants that hold across the entire catalog."""

    def test_keys_are_unique(self):
        keys = [s.key for s in registry.all_settings()]
        assert len(keys) == len(set(keys)), "Duplicate registry key(s) detected"

    def test_env_names_are_non_empty(self):
        for s in registry.all_settings():
            assert s.env, f"Setting {s.key!r} has an empty env name"

    def test_env_names_are_unique(self):
        envs = [s.env for s in registry.all_settings()]
        duplicates = [e for e in set(envs) if envs.count(e) > 1]
        assert not duplicates, f"Duplicate env names: {duplicates}"

    def test_no_extra_session_keys(self):
        """Only the ten tier-3 keys are session-scoped."""
        expected_session = {
            "yandex_quality",
            "yandex_lyrics_format",
            "yandex_cover_resolution",
            "yandex_embed_cover",
            "yandex_skip_existing",
            "yandex_only_music",
            "yandex_stick_to_artist",
            "yandex_clear_comments",
            "ytdlp_format",
            "ytdlp_quality",
        }
        actual_session = set(registry.session_keys())
        assert actual_session == expected_session

    def test_secrets_have_provider(self):
        for s in registry.all_settings():
            if s.secret:
                assert s.provider, f"Secret {s.key!r} must carry a non-empty provider"

    def test_secrets_in_catalog(self):
        secret_keys = {s.key for s in registry.all_settings() if s.secret}
        assert secret_keys == {"yandex_token", "lidarr_api_key", "ytmusic_client_secret"}

    def test_all_settings_have_valid_scope(self):
        for s in registry.all_settings():
            assert s.scope in ("global", "session"), f"{s.key!r} has unknown scope {s.scope!r}"

    def test_all_settings_have_valid_provider(self):
        valid_providers = {"yandex", "ytdlp", "lidarr", "app", "ui"}
        for s in registry.all_settings():
            assert s.provider in valid_providers, f"{s.key!r} has unknown provider {s.provider!r}"

    def test_enum_settings_have_choices(self):
        for s in registry.all_settings():
            if s.type == "enum":
                assert s.choices, f"Enum setting {s.key!r} must have non-empty choices"

    def test_non_enum_non_cover_settings_choices_none(self):
        for s in registry.all_settings():
            if s.type not in ("enum", "cover_resolution"):
                assert s.choices is None, f"{s.key!r} (type={s.type!r}) should have choices=None"

    def test_catalog_count(self):
        """32 settings (3 Tier-1 + 16 Tier-2 + 10 Tier-3 + 2 Tier-4 + 1 Server)."""
        assert len(registry.all_settings()) == 32


class TestAccessors:
    def test_get_returns_setting(self):
        s = registry.get("yandex_token")
        assert isinstance(s, Setting)
        assert s.key == "yandex_token"

    def test_get_missing_returns_none(self):
        assert registry.get("ALBFETCHARR_PORT") is None
        assert registry.get("nonexistent") is None

    def test_all_settings_returns_list_of_settings(self):
        result = registry.all_settings()
        assert all(isinstance(s, Setting) for s in result)

    def test_all_settings_is_copy(self):
        a = registry.all_settings()
        b = registry.all_settings()
        assert a is not b  # must be a fresh list each time

    def test_by_group_keys_match_all_groups(self):
        groups = registry.by_group()
        all_group_names = {s.group for s in registry.all_settings()}
        assert set(groups.keys()) == all_group_names

    def test_by_group_total_count(self):
        groups = registry.by_group()
        total = sum(len(v) for v in groups.values())
        assert total == len(registry.all_settings())

    def test_by_group_known_groups(self):
        groups = registry.by_group()
        expected_groups = {
            "Sources",
            "Lidarr",
            "Download (Yandex)",
            "Download (yt-dlp)",
            "Network",
            "UI",
            "Server",
        }
        assert set(groups.keys()) == expected_groups

    def test_session_keys_returns_list(self):
        keys = registry.session_keys()
        assert isinstance(keys, list)
        assert all(isinstance(k, str) for k in keys)

    def test_is_session_key_true(self):
        assert registry.is_session_key("yandex_quality") is True
        assert registry.is_session_key("ytdlp_format") is True

    def test_is_session_key_false_for_global(self):
        assert registry.is_session_key("yandex_token") is False
        assert registry.is_session_key("enable_yandex") is False

    def test_is_session_key_false_for_missing(self):
        assert registry.is_session_key("unknown_key") is False


class TestValidateValueBool:
    """validate_value for type='bool'."""

    BOOL_SETTING = Setting(
        "enable_yandex",
        "bool",
        "1",
        None,
        "ALBFETCHARR_ENABLE_YANDEX",
        "global",
        False,
        "Sources",
        "app",
    )

    @pytest.mark.parametrize("raw", ["0", "1", "true", "false", "yes", "no"])
    def test_valid_bool_strings(self, raw):
        validate_value(self.BOOL_SETTING, raw)  # must not raise

    @pytest.mark.parametrize("raw", ["True", "False", "YES", "NO", "TRUE"])
    def test_valid_bool_strings_case_insensitive(self, raw):
        validate_value(self.BOOL_SETTING, raw)  # must not raise

    @pytest.mark.parametrize("raw", ["random", "null", "off", "on", "2", "", "none"])
    def test_invalid_bool_strings(self, raw):
        with pytest.raises(ValueError, match="invalid boolean"):
            validate_value(self.BOOL_SETTING, raw)


class TestValidateValueInt:
    """validate_value for type='int'."""

    RETRIES_SETTING = Setting(
        "ytdlp_retries",
        "int",
        "3",
        None,
        "ALBFETCHARR_YTDLP_RETRIES",
        "global",
        False,
        "Download (yt-dlp)",
        "ytdlp",
        min_val=1,
    )
    DELAY_SETTING = Setting(
        "yandex_delay",
        "int",
        "0",
        None,
        "ALBFETCHARR_DELAY",
        "global",
        False,
        "Download (Yandex)",
        "yandex",
        min_val=0,
    )
    PLAIN_INT_SETTING = Setting(
        "ytdlp_quality",
        "int",
        "192",
        None,
        "ALBFETCHARR_YTDLP_QUALITY",
        "session",
        False,
        "Download (yt-dlp)",
        "ytdlp",
        min_val=0,
    )

    @pytest.mark.parametrize("raw", ["1", "3", "10", "100"])
    def test_valid_int_strings(self, raw):
        validate_value(self.RETRIES_SETTING, raw)  # must not raise

    @pytest.mark.parametrize("raw", ["foo", "1.5", "", "abc"])
    def test_invalid_int_not_parseable(self, raw):
        with pytest.raises(ValueError, match="invalid integer"):
            validate_value(self.RETRIES_SETTING, raw)

    def test_int_below_min(self):
        with pytest.raises(ValueError, match="below minimum"):
            validate_value(self.RETRIES_SETTING, "0")

    def test_int_at_min(self):
        validate_value(self.RETRIES_SETTING, "1")  # must not raise

    def test_int_zero_with_min_zero(self):
        validate_value(self.DELAY_SETTING, "0")  # must not raise

    def test_int_no_bounds(self):
        validate_value(self.PLAIN_INT_SETTING, "0")  # must not raise
        validate_value(self.PLAIN_INT_SETTING, "320")  # must not raise

    def test_int_max_bound(self):
        bounded = Setting(
            "test_key",
            "int",
            "5",
            None,
            "TEST_KEY",
            "global",
            False,
            "UI",
            "ui",
            min_val=0,
            max_val=10,
        )
        validate_value(bounded, "10")  # must not raise
        with pytest.raises(ValueError, match="above maximum"):
            validate_value(bounded, "11")


class TestValidateValueEnum:
    """validate_value for type='enum'."""

    QUALITY_SETTING = Setting(
        "yandex_quality",
        "enum",
        "2",
        ["0", "1", "2"],
        "YANDEX_MUSIC_QUALITY",
        "session",
        False,
        "Download (Yandex)",
        "yandex",
    )
    LYRICS_SETTING = Setting(
        "yandex_lyrics_format",
        "enum",
        "lrc",
        ["none", "text", "lrc"],
        "ALBFETCHARR_LYRICS_FORMAT",
        "session",
        False,
        "Download (Yandex)",
        "yandex",
    )

    @pytest.mark.parametrize("raw", ["0", "1", "2"])
    def test_valid_quality_values(self, raw):
        validate_value(self.QUALITY_SETTING, raw)  # must not raise

    @pytest.mark.parametrize("raw", ["none", "text", "lrc"])
    def test_valid_lyrics_values(self, raw):
        validate_value(self.LYRICS_SETTING, raw)  # must not raise

    @pytest.mark.parametrize("raw", ["3", "hi", "best", "", "flac"])
    def test_invalid_quality_values(self, raw):
        with pytest.raises(ValueError, match="invalid value"):
            validate_value(self.QUALITY_SETTING, raw)

    @pytest.mark.parametrize("raw", ["None", "Text", "LRC", "xml"])
    def test_invalid_lyrics_values(self, raw):
        with pytest.raises(ValueError, match="invalid value"):
            validate_value(self.LYRICS_SETTING, raw)


class TestValidateValueCoverResolution:
    """validate_value for type='cover_resolution'."""

    COVER_SETTING = Setting(
        "yandex_cover_resolution",
        "cover_resolution",
        "400",
        None,
        "ALBFETCHARR_COVER_RESOLUTION",
        "session",
        False,
        "Download (Yandex)",
        "yandex",
    )

    @pytest.mark.parametrize("raw", ["original", "400", "1", "1000", "200"])
    def test_valid_cover_resolution(self, raw):
        validate_value(self.COVER_SETTING, raw)  # must not raise

    @pytest.mark.parametrize("raw", ["0", "-1", "foo", "", "Original", "400px"])
    def test_invalid_cover_resolution(self, raw):
        with pytest.raises(ValueError, match="invalid cover resolution"):
            validate_value(self.COVER_SETTING, raw)


class TestValidateValueStr:
    """validate_value for type='str' — any non-None string is valid."""

    STR_SETTING = Setting(
        "yandex_path_pattern",
        "str",
        None,
        None,
        "ALBFETCHARR_YANDEX_PATH_PATTERN",
        "global",
        False,
        "Download (Yandex)",
        "yandex",
    )

    @pytest.mark.parametrize("raw", ["", "some/path", "#artist/#album", "%(artist)s"])
    def test_any_string_is_valid(self, raw):
        validate_value(self.STR_SETTING, raw)  # must not raise


class TestSpecificSettings:
    """Spot-check that specific catalog entries have the expected attributes."""

    def test_yandex_token_is_secret(self):
        s = registry.get("yandex_token")
        assert s.secret is True
        assert s.provider == "yandex"
        assert s.env == "YANDEX_MUSIC_TOKEN"

    def test_lidarr_api_key_is_secret(self):
        s = registry.get("lidarr_api_key")
        assert s.secret is True
        assert s.provider == "lidarr"

    def test_ytmusic_client_secret_is_secret(self):
        s = registry.get("ytmusic_client_secret")
        assert s.secret is True
        assert s.provider == "ytdlp"

    def test_enable_yandex_defaults_and_env(self):
        s = registry.get("enable_yandex")
        assert s.default == "1"
        assert s.env == "ALBFETCHARR_ENABLE_YANDEX"
        assert s.type == "bool"
        assert s.scope == "global"

    def test_yandex_net_timeout_renamed_env(self):
        s = registry.get("yandex_net_timeout")
        assert s.env == "ALBFETCHARR_YANDEX_TIMEOUT"
        assert s.min_val == 1

    def test_yandex_net_tries_renamed_env(self):
        s = registry.get("yandex_net_tries")
        assert s.env == "ALBFETCHARR_YANDEX_TRIES"

    def test_yandex_net_retry_delay_renamed_env(self):
        s = registry.get("yandex_net_retry_delay")
        assert s.env == "ALBFETCHARR_YANDEX_RETRY_DELAY"

    def test_yandex_path_pattern_removed(self):
        assert registry.get("yandex_path_pattern") is None

    def test_ytdlp_path_pattern_removed(self):
        assert registry.get("ytdlp_path_pattern") is None

    def test_ytdlp_retries_min_is_1(self):
        s = registry.get("ytdlp_retries")
        assert s.min_val == 1
        assert s.default == "3"

    def test_ytdlp_format_choices(self):
        s = registry.get("ytdlp_format")
        assert s.choices == ["best", "opus", "m4a", "mp3"]
        assert "flac" not in s.choices
        assert "vorbis" not in s.choices
        assert "aac" not in s.choices
        assert "wav" not in s.choices
        assert s.default == "opus"
        assert s.scope == "session"

    def test_default_lang_choices(self):
        s = registry.get("default_lang")
        assert s.choices == ["en", "ru"]
        assert s.default == "en"

    def test_default_theme_choices(self):
        s = registry.get("default_theme")
        assert s.choices == ["system", "light", "dark"]
        assert s.default == "system"

    def test_yandex_compat_level_enum(self):
        s = registry.get("yandex_compat_level")
        assert s.type == "enum"
        assert s.choices == ["0", "1"]

    def test_yandex_cover_resolution_type(self):
        s = registry.get("yandex_cover_resolution")
        assert s.type == "cover_resolution"
        assert s.scope == "session"

    def test_app_log_level_setting(self):
        s = registry.get("app_log_level")
        assert s.type == "enum"
        assert s.choices == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        assert s.default == "INFO"
        assert s.env == "ALBFETCHARR_LOG_LEVEL"
        assert s.scope == "global"
        assert s.provider == "app"
        assert s.group == "Server"
