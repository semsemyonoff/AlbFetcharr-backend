"""Tests for albfetcharr.settings.store."""

import pytest

from albfetcharr.settings import store


@pytest.fixture
def db(tmp_path):
    """Return a path to a fresh temporary DB file."""
    return str(tmp_path / "test_settings.db")


class TestTableAutoCreate:
    def test_get_raw_on_new_db_returns_none(self, db):
        assert store.get_raw("missing_key", db_path=db) is None

    def test_set_creates_table_implicitly(self, db):
        store.set_raw("k", "v", db_path=db)
        result = store.get_raw("k", db_path=db)
        assert result is not None


class TestSetGetRoundTrip:
    def test_set_then_get(self, db):
        store.set_raw("mykey", "myvalue", db_path=db)
        assert store.get_raw("mykey", db_path=db) == ("myvalue", False)

    def test_get_missing_returns_none(self, db):
        assert store.get_raw("nonexistent", db_path=db) is None

    def test_upsert_overwrites(self, db):
        store.set_raw("k", "first", db_path=db)
        store.set_raw("k", "second", db_path=db)
        assert store.get_raw("k", db_path=db) == ("second", False)


class TestIsSecretFlag:
    def test_secret_flag_stored_true(self, db):
        store.set_raw("tok", "secret_val", is_secret=True, db_path=db)
        value, is_secret = store.get_raw("tok", db_path=db)
        assert value == "secret_val"
        assert is_secret is True

    def test_non_secret_flag_stored_false(self, db):
        store.set_raw("plain", "open", is_secret=False, db_path=db)
        _, is_secret = store.get_raw("plain", db_path=db)
        assert is_secret is False

    def test_upsert_updates_is_secret(self, db):
        store.set_raw("k", "v", is_secret=False, db_path=db)
        store.set_raw("k", "v2", is_secret=True, db_path=db)
        _, is_secret = store.get_raw("k", db_path=db)
        assert is_secret is True


class TestDelete:
    def test_delete_existing_returns_true(self, db):
        store.set_raw("k", "v", db_path=db)
        assert store.delete("k", db_path=db) is True

    def test_delete_removes_key(self, db):
        store.set_raw("k", "v", db_path=db)
        store.delete("k", db_path=db)
        assert store.get_raw("k", db_path=db) is None

    def test_delete_absent_returns_false(self, db):
        assert store.delete("never_set", db_path=db) is False


class TestAllRaw:
    def test_empty_db_returns_empty_dict(self, db):
        assert store.all_raw(db_path=db) == {}

    def test_returns_all_keys(self, db):
        store.set_raw("a", "1", db_path=db)
        store.set_raw("b", "2", is_secret=True, db_path=db)
        result = store.all_raw(db_path=db)
        assert set(result.keys()) == {"a", "b"}

    def test_shape_value_and_is_secret(self, db):
        store.set_raw("x", "hello", is_secret=False, db_path=db)
        store.set_raw("y", "world", is_secret=True, db_path=db)
        result = store.all_raw(db_path=db)
        assert result["x"] == ("hello", False)
        assert result["y"] == ("world", True)

    def test_deleted_key_absent_from_all_raw(self, db):
        store.set_raw("k", "v", db_path=db)
        store.delete("k", db_path=db)
        assert "k" not in store.all_raw(db_path=db)
