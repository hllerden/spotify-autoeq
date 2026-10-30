"""Genre resolution: cache first, then the provider chain."""

from __future__ import annotations

import logging
from typing import NamedTuple, Optional, Sequence

from .cache import GenreCache
from .ports import GenreProvider, ProviderError
from .validation import clean_genres, normalize_artist

_LOG = logging.getLogger(__name__)


class Resolution(NamedTuple):
    genres: "tuple[str, ...]"
    source: str
    """Provider name, ``""`` for older cache entries, ``"none"`` when nothing was found."""
    cached: bool


class GenreResolver:
    """Resolves the genres of an artist.

    Providers are tried in order; the first one returning at least one useful
    genre wins. If every provider answered "unknown" the negative result is
    cached; if any provider failed (network), nothing is cached so the next
    track retries."""

    def __init__(self, providers: Sequence[GenreProvider], cache: GenreCache) -> None:
        self._providers = list(providers)
        self._cache = cache

    def resolve(self, artist: str, title: str) -> "tuple[str, ...]":
        return self.resolve_detailed(artist, title).genres

    def resolve_detailed(self, artist: str, title: str) -> Resolution:
        """Like :meth:`resolve`, but also reports where the answer came from."""
        key = normalize_artist(artist)
        if not key:
            return Resolution((), "none", False)
        cached = self._cache.get(key)
        if cached is not None:
            _LOG.debug("cache hit for %r: %s", key, cached.genres or "negative")
            return Resolution(cached.genres, cached.source if cached.genres else "none", True)
        failed = False
        for provider in self._providers:
            try:
                raw = provider.lookup(artist, title)
            except ProviderError as exc:
                failed = True
                _LOG.warning("%s failed: %s", provider.name, exc)
                continue
            except Exception:  # noqa: BLE001 - one broken provider must not stop the chain
                failed = True
                _LOG.exception("%s raised unexpectedly", provider.name)
                continue
            genres = clean_genres(list(raw or ()))
            if genres:
                _LOG.info("%s -> %s via %s", artist, ", ".join(genres), provider.name)
                self._cache.put(key, genres, provider.name)
                return Resolution(genres, provider.name, False)
        if not failed:
            self._cache.put(key, ())
        _LOG.info("no genre found for %s", artist)
        return Resolution((), "none", False)
