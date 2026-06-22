import pytest

from albfetcharr.sources import clear_registry


@pytest.fixture(scope="function", autouse=True)
def _clean_registry():
    """Autouse fixture that clears the provider registry before each test.

    This ensures test isolation: each test starts with an empty registry,
    preventing test pollution and allowing tests to register their own fake providers.
    """
    clear_registry()
    yield
    clear_registry()


@pytest.fixture(scope="function", autouse=True)
def _isolate_db_path(tmp_path, monkeypatch):
    """Autouse fixture that points the settings store at a per-test temp DB.

    Without this, any code path that resolves config without mocking the store
    (e.g. cli.main → resolve_app_config → store.all_raw) falls back to the default
    /config/albfetcharr.db and tries to os.makedirs("/config"). That happens to
    succeed on a root CI runner (Forgejo) but raises PermissionError on a non-root
    one (GitHub Actions). Tests that need a specific path still override this env
    var via their own monkeypatch (function-scoped, applied after this fixture).
    """
    monkeypatch.setenv("ALBFETCHARR_DB_PATH", str(tmp_path / "settings.db"))
