import logging

from .base import LogFn, Match, SourceProvider

__all__ = [
    "LogFn",
    "Match",
    "SourceProvider",
    "register",
    "get_provider",
    "all_providers",
    "clear_registry",
    "bootstrap_default_providers",
]

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, SourceProvider] = {}


def register(provider: SourceProvider, *, replace: bool = False) -> None:
    """Register a source provider in the global registry.

    Args:
        provider: The provider instance to register.
        replace: If True, overwrite an existing provider with the same id.
                 If False, raise ValueError if the id is already registered.

    Raises:
        ValueError: If the provider id is already registered and replace=False.
    """
    if provider.id in _REGISTRY and not replace:
        raise ValueError(f"Provider {provider.id!r} already registered")
    _REGISTRY[provider.id] = provider


def get_provider(provider_id: str) -> SourceProvider:
    """Get a provider by id.

    Args:
        provider_id: The provider id (e.g. "yandex").

    Returns:
        The SourceProvider instance.

    Raises:
        KeyError: If the provider is not registered.
    """
    return _REGISTRY[provider_id]


def all_providers() -> list[SourceProvider]:
    """Return all registered providers.

    Returns:
        List of SourceProvider instances.
    """
    return list(_REGISTRY.values())


def clear_registry() -> None:
    """Clear the provider registry. Used by tests for isolation."""
    _REGISTRY.clear()


def bootstrap_default_providers() -> None:
    """Register all providers based on current resolved config.

    Called explicitly from cli.main() and web.app.create_app(),
    NOT at module import — this keeps the test registry empty by default,
    preventing test pollution.

    Re-entrant/idempotent: builds a fresh local dict, then atomically swaps
    _REGISTRY so concurrent all_providers()/get_provider() readers always see a
    consistent snapshot and now-disabled providers are removed without any lock.
    """
    global _REGISTRY

    from albfetcharr.settings.resolver import resolve_app_config
    from albfetcharr.sources.soundcloud import SoundCloudProvider
    from albfetcharr.sources.yandex import YandexMusicProvider
    from albfetcharr.sources.youtube_music import YouTubeMusicProvider

    cfg = resolve_app_config()
    fresh: dict[str, SourceProvider] = {}

    if cfg.enable_yandex:
        if cfg.yandex_token:
            fresh["yandex"] = YandexMusicProvider(cfg.yandex_token, cfg.yandex_options)
        else:
            logger.warning(
                "Yandex Music is enabled (ALBFETCHARR_ENABLE_YANDEX) but no token is set "
                "(YANDEX_MUSIC_TOKEN) — provider not registered"
            )

    if cfg.enable_youtube_music:
        fresh["youtube_music"] = YouTubeMusicProvider(cfg.ytdlp_options)

    if cfg.enable_soundcloud:
        fresh["soundcloud"] = SoundCloudProvider(cfg.ytdlp_options)

    _REGISTRY = fresh
