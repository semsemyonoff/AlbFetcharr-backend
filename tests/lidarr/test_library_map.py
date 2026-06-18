"""Tests for library_map module."""

from albfetcharr.lidarr.library_map import (
    parse_library_map_str,
    resolve_library_path,
    validate_library_map,
)


class TestParseLibraryMapStr:
    def test_none_input_returns_empty(self):
        """None input returns empty dict."""
        assert parse_library_map_str(None) == {}

    def test_empty_string_returns_empty(self):
        """Empty string returns empty dict."""
        assert parse_library_map_str("") == {}

    def test_single_pair(self):
        """Parse a single mapping pair."""
        assert parse_library_map_str("/mnt/lidarr=/mnt/albfetcharr") == {
            "/mnt/lidarr": "/mnt/albfetcharr"
        }

    def test_multiple_pairs(self):
        """Parse multiple comma-separated pairs."""
        result = parse_library_map_str("/mnt/lidarr=/mnt/albfetcharr,/data/music=/mnt/music")
        assert result == {
            "/mnt/lidarr": "/mnt/albfetcharr",
            "/data/music": "/mnt/music",
        }

    def test_trailing_slashes_removed(self):
        """Trailing slashes are normalized away."""
        result = parse_library_map_str("/mnt/lidarr/=/mnt/albfetcharr/")
        assert result == {"/mnt/lidarr": "/mnt/albfetcharr"}

    def test_whitespace_around_pairs(self):
        """Whitespace around pairs is stripped."""
        result = parse_library_map_str(
            "  /mnt/lidarr=/mnt/albfetcharr  ,  /data/music=/mnt/music  "
        )
        assert result == {
            "/mnt/lidarr": "/mnt/albfetcharr",
            "/data/music": "/mnt/music",
        }

    def test_ignores_malformed_pairs(self):
        """Pairs without '=' are silently ignored."""
        result = parse_library_map_str("/mnt/lidarr=/mnt/albfetcharr,invalid_pair")
        assert result == {"/mnt/lidarr": "/mnt/albfetcharr"}


class TestResolveLibraryPath:
    def test_empty_mapping_returns_original(self):
        """No mapping returns original path."""
        path = "/data/library/artist/album"
        assert resolve_library_path(path, {}) == path

    def test_none_mapping_returns_original(self):
        """None mapping returns original path (does not read env)."""
        assert resolve_library_path("/data/library/artist/album") == "/data/library/artist/album"

    def test_none_mapping_ignores_env(self, monkeypatch):
        """None mapping returns identity even when env var is set (env read removed)."""
        monkeypatch.setenv("ALBFETCHARR_LIBRARY_MAP", "/mnt/lidarr=/mnt/albfetcharr")
        assert resolve_library_path("/mnt/lidarr/artist") == "/mnt/lidarr/artist"

    def test_exact_prefix_match(self):
        """Exact prefix match in the path."""
        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        result = resolve_library_path("/mnt/lidarr", mapping)
        assert result == "/mnt/albfetcharr"

    def test_prefix_with_trailing_content(self):
        """Prefix match with content after it."""
        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        result = resolve_library_path("/mnt/lidarr/artist/album", mapping)
        assert result == "/mnt/albfetcharr/artist/album"

    def test_longest_prefix_wins(self):
        """When multiple prefixes match, longest wins."""
        mapping = {
            "/mnt": "/mnt1",
            "/mnt/lidarr": "/mnt2",
            "/mnt/lidarr/music": "/mnt3",
        }
        result = resolve_library_path("/mnt/lidarr/music/artist", mapping)
        assert result == "/mnt3/artist"

    def test_no_matching_prefix(self):
        """No matching prefix returns original."""
        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        result = resolve_library_path("/data/music/artist", mapping)
        assert result == "/data/music/artist"

    def test_multiple_slashes_not_prefix_matched(self):
        """Path must have proper slash boundary."""
        mapping = {"/mnt/lid": "/mnt/alb"}
        result = resolve_library_path("/mnt/lidarr/artist", mapping)
        assert result == "/mnt/lidarr/artist"  # /mnt/lid does not match /mnt/lidarr


class TestValidateLibraryMap:
    def test_none_mapping_no_warning(self, caplog):
        """None mapping produces no warnings (env read removed)."""
        import logging

        root_folders = [{"path": "/mnt/lidarr"}]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders)
        assert caplog.records == []

    def test_none_mapping_ignores_env(self, monkeypatch, caplog):
        """None mapping skips validation even when env var is set."""
        import logging

        monkeypatch.setenv("ALBFETCHARR_LIBRARY_MAP", "/mnt/lidarr=/mnt/albfetcharr")
        root_folders = [{"path": "/data/music"}]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders)
        assert caplog.records == []

    def test_empty_mapping_no_warning(self, capsys):
        """Empty mapping produces no warnings."""
        root_folders = [{"path": "/mnt/lidarr"}]
        validate_library_map(root_folders, {})
        assert capsys.readouterr().err == ""

    def test_empty_root_folders_no_warning(self, capsys):
        """Empty root folders produces no warnings."""
        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        validate_library_map([], mapping)
        assert capsys.readouterr().err == ""

    def test_mapped_root_folder_no_warning(self, caplog):
        """Root folder in mapping produces no warning."""
        import logging

        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        root_folders = [{"path": "/mnt/lidarr"}]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders, mapping)
        assert caplog.records == []

    def test_unmapped_root_folder_warning(self, caplog):
        """Root folder not in mapping produces warning."""
        import logging

        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        root_folders = [{"path": "/data/music"}]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders, mapping)
        messages = " ".join(r.message for r in caplog.records)
        assert "/data/music" in messages
        assert "ALBFETCHARR_LIBRARY_MAP" in messages

    def test_multiple_root_folders(self, caplog):
        """Multiple root folders: only unmapped ones warn."""
        import logging

        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        root_folders = [
            {"path": "/mnt/lidarr"},
            {"path": "/data/music"},
            {"path": "/media/library"},
        ]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders, mapping)
        messages = " ".join(r.message for r in caplog.records)
        assert "/data/music" in messages
        assert "/media/library" in messages
        assert "/mnt/lidarr" not in messages  # this one is mapped

    def test_trailing_slashes_normalized(self, caplog):
        """Trailing slashes in root folder paths are normalized."""
        import logging

        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        root_folders = [{"path": "/mnt/lidarr/"}]  # trailing slash
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders, mapping)
        assert caplog.records == []  # should match after normalization

    def test_missing_path_key_ignored(self, caplog):
        """Root folder without 'path' key is silently ignored."""
        import logging

        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        root_folders = [{"id": 1}, {"path": "/data/music"}]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders, mapping)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("/data/music" in r.message for r in warnings)
        assert len(warnings) == 1  # only one warning, not two

    def test_empty_path_value_ignored(self, caplog):
        """Root folder with empty path is ignored."""
        import logging

        mapping = {"/mnt/lidarr": "/mnt/albfetcharr"}
        root_folders = [{"path": ""}, {"path": "/data/music"}]
        with caplog.at_level(logging.WARNING, logger="albfetcharr"):
            validate_library_map(root_folders, mapping)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("/data/music" in r.message for r in warnings)
        assert len(warnings) == 1  # only one warning
