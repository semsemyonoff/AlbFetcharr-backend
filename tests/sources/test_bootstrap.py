"""Tests for bootstrap_default_providers() — enable/token matrix and idempotent swap."""

import logging
from unittest.mock import MagicMock, patch

from albfetcharr.config import AppConfig, LidarrConfig, YandexOptions, YtDlpOptions
from albfetcharr.sources import all_providers, bootstrap_default_providers


def _make_cfg(
    *,
    enable_yandex: bool = True,
    yandex_token: str | None = "tok",
    enable_youtube_music: bool = True,
    enable_soundcloud: bool = True,
) -> AppConfig:
    lidarr = LidarrConfig(base_url="", api_key="", import_path="", library_map=None)
    yopts = YandexOptions(
        quality="2",
        lyrics_format="lrc",
        cover_resolution="400",
        embed_cover=False,
        skip_existing=True,
        delay="0",
        compat_level="1",
        timeout="20",
        tries="20",
        retry_delay="5",
        stick_to_artist=False,
        only_music=False,
        unsafe_path=False,
        path_pattern=None,
        download_dir="/downloads",
        clear_comments=False,
    )
    ytopts = YtDlpOptions(
        download_dir="/downloads",
        audio_format="flac",
        audio_quality=192,
        path_pattern="%(artist)s/%(album)s/%(track_number)02d - %(title)s.%(ext)s",
        cookies_file=None,
        download_retries=3,
        ytmusic_oauth_file="/config/ytmusic_oauth.json",
        ytmusic_client_id=None,
        ytmusic_client_secret=None,
    )
    return AppConfig(
        lidarr=lidarr,
        yandex_token=yandex_token,
        yandex_options=yopts,
        ytdlp_options=ytopts,
        enable_yandex=enable_yandex,
        enable_youtube_music=enable_youtube_music,
        enable_soundcloud=enable_soundcloud,
    )


PATCH_RESOLVE = "albfetcharr.settings.resolver.resolve_app_config"
PATCH_YANDEX = "albfetcharr.sources.yandex.YandexMusicProvider"
PATCH_YTMUSIC = "albfetcharr.sources.youtube_music.YouTubeMusicProvider"
PATCH_SC = "albfetcharr.sources.soundcloud.SoundCloudProvider"


class TestBootstrapYandexMatrix:
    def test_enabled_with_token_registers_yandex(self):
        cfg = _make_cfg(enable_yandex=True, yandex_token="secret")
        fake_provider = MagicMock()
        fake_provider.id = "yandex"

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX, return_value=fake_provider) as MockYandex,
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        MockYandex.assert_called_once_with("secret", cfg.yandex_options)
        ids = {p.id for p in all_providers()}
        assert "yandex" in ids

    def test_enabled_no_token_skips_yandex_and_warns(self, caplog):
        cfg = _make_cfg(enable_yandex=True, yandex_token=None)

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX) as MockYandex,
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
            caplog.at_level(logging.WARNING, logger="albfetcharr.sources"),
        ):
            bootstrap_default_providers()

        MockYandex.assert_not_called()
        ids = {p.id for p in all_providers()}
        assert "yandex" not in ids
        assert any(
            "no token" in r.message.lower() or "not registered" in r.message.lower()
            for r in caplog.records
        )

    def test_disabled_yandex_skips_regardless_of_token(self):
        cfg = _make_cfg(enable_yandex=False, yandex_token="secret")

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX) as MockYandex,
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        MockYandex.assert_not_called()
        ids = {p.id for p in all_providers()}
        assert "yandex" not in ids


class TestBootstrapOtherToggles:
    def test_youtube_music_disabled_skips(self):
        cfg = _make_cfg(enable_youtube_music=False)

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC) as MockYtMusc,
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        MockYtMusc.assert_not_called()
        ids = {p.id for p in all_providers()}
        assert "youtube_music" not in ids

    def test_soundcloud_disabled_skips(self):
        cfg = _make_cfg(enable_soundcloud=False)

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC) as MockSC,
        ):
            bootstrap_default_providers()

        MockSC.assert_not_called()
        ids = {p.id for p in all_providers()}
        assert "soundcloud" not in ids

    def test_all_enabled_registers_all_three(self):
        cfg = _make_cfg()

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        ids = {p.id for p in all_providers()}
        assert ids == {"yandex", "youtube_music", "soundcloud"}

    def test_all_disabled_results_in_empty_registry(self):
        cfg = _make_cfg(enable_yandex=False, enable_youtube_music=False, enable_soundcloud=False)

        with patch(PATCH_RESOLVE, return_value=cfg):
            bootstrap_default_providers()

        assert all_providers() == []


class TestBootstrapIdempotentSwap:
    def test_rerun_adds_newly_enabled_provider(self):
        cfg_without_sc = _make_cfg(enable_soundcloud=False)
        cfg_with_sc = _make_cfg(enable_soundcloud=True)

        with (
            patch(PATCH_RESOLVE, return_value=cfg_without_sc),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        ids_before = {p.id for p in all_providers()}
        assert "soundcloud" not in ids_before

        with (
            patch(PATCH_RESOLVE, return_value=cfg_with_sc),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        ids_after = {p.id for p in all_providers()}
        assert "soundcloud" in ids_after

    def test_rerun_drops_newly_disabled_provider(self):
        cfg_with_sc = _make_cfg(enable_soundcloud=True)
        cfg_without_sc = _make_cfg(enable_soundcloud=False)

        with (
            patch(PATCH_RESOLVE, return_value=cfg_with_sc),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        ids_before = {p.id for p in all_providers()}
        assert "soundcloud" in ids_before

        with (
            patch(PATCH_RESOLVE, return_value=cfg_without_sc),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC),
        ):
            bootstrap_default_providers()

        ids_after = {p.id for p in all_providers()}
        assert "soundcloud" not in ids_after
        # Registry is non-empty — other providers still present.
        assert len(ids_after) > 0

    def test_rerun_keeps_registry_non_empty_during_swap(self):
        """Registry should never appear empty to a reader between two bootstrap calls."""
        cfg = _make_cfg()

        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()
            snapshot_mid = {p.id for p in all_providers()}

        # A second run with same config should still have all providers.
        with (
            patch(PATCH_RESOLVE, return_value=cfg),
            patch(PATCH_YANDEX, return_value=MagicMock(id="yandex")),
            patch(PATCH_YTMUSIC, return_value=MagicMock(id="youtube_music")),
            patch(PATCH_SC, return_value=MagicMock(id="soundcloud")),
        ):
            bootstrap_default_providers()

        assert snapshot_mid == {"yandex", "youtube_music", "soundcloud"}
        assert {p.id for p in all_providers()} == {"yandex", "youtube_music", "soundcloud"}
