"""Tests for albfetcharr.settings.crypto."""

import pytest
from cryptography.fernet import Fernet

from albfetcharr.settings import crypto


def _gen_key() -> str:
    return Fernet.generate_key().decode()


class TestIsEnabled:
    def test_false_when_key_unset(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_SECRET_KEY", raising=False)
        assert crypto.is_enabled() is False

    def test_false_when_key_invalid(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", "not-a-valid-fernet-key")
        assert crypto.is_enabled() is False

    def test_true_with_valid_key(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        assert crypto.is_enabled() is True


class TestEncryptDecrypt:
    def test_round_trip(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        plaintext = "super-secret-token"
        ciphertext = crypto.encrypt(plaintext)
        assert ciphertext != plaintext
        assert crypto.decrypt(ciphertext) == plaintext

    def test_encrypt_raises_without_key(self, monkeypatch):
        monkeypatch.delenv("ALBFETCHARR_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ALBFETCHARR_SECRET_KEY"):
            crypto.encrypt("secret")

    def test_encrypt_raises_with_invalid_key(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", "garbage")
        with pytest.raises(RuntimeError, match="ALBFETCHARR_SECRET_KEY"):
            crypto.encrypt("secret")

    def test_decrypt_returns_none_without_key(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        ciphertext = crypto.encrypt("value")

        monkeypatch.delenv("ALBFETCHARR_SECRET_KEY", raising=False)
        result = crypto.decrypt(ciphertext)
        assert result is None

    def test_decrypt_returns_none_tampered_ciphertext(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        result = crypto.decrypt("gAAAAABtampered==")
        assert result is None

    def test_decrypt_returns_none_wrong_key(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        ciphertext = crypto.encrypt("value")

        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        result = crypto.decrypt(ciphertext)
        assert result is None

    def test_decrypt_empty_string_returns_none(self, monkeypatch):
        monkeypatch.setenv("ALBFETCHARR_SECRET_KEY", _gen_key())
        assert crypto.decrypt("") is None


class TestMask:
    def test_long_value_shows_last_4(self):
        assert crypto.mask("abcdefgh") == "•••efgh"

    def test_exactly_4_chars(self):
        assert crypto.mask("abcd") == "•••abcd"

    def test_short_value_shows_all(self):
        assert crypto.mask("abc") == "•••abc"

    def test_single_char(self):
        assert crypto.mask("x") == "•••x"

    def test_empty_string(self):
        assert crypto.mask("") == "•••"

    def test_token_like(self):
        result = crypto.mask("1234567890abcdef3f9a")
        assert result == "•••3f9a"
