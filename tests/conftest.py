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
