"""Tests for albfetcharr.settings.file_status helpers."""

import json

from albfetcharr.settings.file_status import cookies_file_status, oauth_file_status


class TestOauthFileStatus:
    def test_missing_when_path_is_none(self):
        assert oauth_file_status(None) == "missing"

    def test_missing_when_path_is_empty(self):
        assert oauth_file_status("") == "missing"

    def test_missing_when_file_absent(self, tmp_path):
        assert oauth_file_status(str(tmp_path / "no_file.json")) == "missing"

    def test_ok_when_valid_json(self, tmp_path):
        f = tmp_path / "oauth.json"
        f.write_text(json.dumps({"access_token": "tok"}))
        assert oauth_file_status(str(f)) == "ok"

    def test_invalid_when_malformed_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not { valid json")
        assert oauth_file_status(str(f)) == "invalid"

    def test_invalid_when_empty_file(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("")
        assert oauth_file_status(str(f)) == "invalid"


class TestCookiesFileStatus:
    def test_missing_when_path_is_none(self):
        assert cookies_file_status(None) == "missing"

    def test_missing_when_path_is_empty(self):
        assert cookies_file_status("") == "missing"

    def test_missing_when_file_absent(self, tmp_path):
        assert cookies_file_status(str(tmp_path / "no_cookies.txt")) == "missing"

    def test_found_when_file_exists(self, tmp_path):
        f = tmp_path / "cookies.txt"
        f.write_text("# Netscape HTTP Cookie File\n")
        assert cookies_file_status(str(f)) == "found"

    def test_found_even_when_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert cookies_file_status(str(f)) == "found"
