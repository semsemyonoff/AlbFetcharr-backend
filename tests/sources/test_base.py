import pytest

from albfetcharr.sources import (
    Match,
    SourceProvider,
    all_providers,
    clear_registry,
    get_provider,
    register,
)


class DummyProvider(SourceProvider):
    """A fake provider for testing the registry."""

    id = "dummy"
    name = "Dummy Provider"

    def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
        return [
            Match(
                source="dummy",
                url="https://dummy.example/album/1",
                title="Test Album",
                artists=artist,
                cover_url=None,
                year=None,
                track_count=None,
            )
        ]

    def download(self, match: Match, *, quality: str | None = None, log=None) -> bool:
        return True


class TestSourceProviderRegistry:
    def test_register_and_retrieve(self):
        """Test registering a provider and retrieving it by id."""
        provider = DummyProvider()
        register(provider)
        retrieved = get_provider("dummy")
        assert retrieved is provider
        assert retrieved.id == "dummy"
        assert retrieved.name == "Dummy Provider"

    def test_register_duplicate_raises_error(self):
        """Test that registering a duplicate id without replace=True raises ValueError."""
        provider1 = DummyProvider()
        register(provider1)
        provider2 = DummyProvider()
        with pytest.raises(ValueError, match="already registered"):
            register(provider2)

    def test_register_replace(self):
        """Test that replace=True allows overwriting an existing provider."""
        provider1 = DummyProvider()
        register(provider1)
        provider2 = DummyProvider()
        register(provider2, replace=True)
        retrieved = get_provider("dummy")
        assert retrieved is provider2

    def test_get_missing_provider_raises_keyerror(self):
        """Test that retrieving a non-existent provider raises KeyError."""
        with pytest.raises(KeyError):
            get_provider("nonexistent")

    def test_all_providers_empty_registry(self):
        """Test that all_providers returns an empty list for a clean registry."""
        providers = all_providers()
        assert providers == []

    def test_all_providers_multiple(self):
        """Test that all_providers returns all registered providers."""

        class AnotherProvider(SourceProvider):
            id = "another"
            name = "Another Provider"

            def search(self, artist: str, album: str, limit: int = 5) -> list[Match]:
                return []

            def download(self, match: Match, *, quality: str | None = None, log=None) -> bool:
                return True

        provider1 = DummyProvider()
        provider2 = AnotherProvider()
        register(provider1)
        register(provider2)
        providers = all_providers()
        assert len(providers) == 2
        ids = {p.id for p in providers}
        assert ids == {"dummy", "another"}

    def test_clear_registry(self):
        """Test that clear_registry empties the registry."""
        register(DummyProvider())
        assert len(all_providers()) == 1
        clear_registry()
        assert len(all_providers()) == 0

    def test_match_dataclass(self):
        """Test the Match dataclass."""
        match = Match(
            source="test",
            url="https://test.example/album/1",
            title="Album Title",
            artists="Artist A, Artist B",
            cover_url="https://test.example/cover.jpg",
            year=2023,
            track_count=12,
        )
        assert match.source == "test"
        assert match.url == "https://test.example/album/1"
        assert match.title == "Album Title"
        assert match.artists == "Artist A, Artist B"
        assert match.cover_url == "https://test.example/cover.jpg"
        assert match.year == 2023
        assert match.track_count == 12

    def test_match_optional_fields_none(self):
        """Test Match with None for optional fields."""
        match = Match(
            source="test",
            url="https://test.example/album/1",
            title="Album Title",
            artists="Artist A",
            cover_url=None,
            year=None,
            track_count=None,
        )
        assert match.cover_url is None
        assert match.year is None
        assert match.track_count is None
