"""Builds the real components from a :class:`Config`."""

from __future__ import annotations

import logging
from typing import Optional

from spotify_autoeq.modules.eq_controller import (
    BackendError, EqController, EqProfile, PulseEffectsBackend, builtin_profiles)
from spotify_autoeq.modules.genre_resolver import (
    DeezerProvider, GenreCache, GenreProvider, GenreResolver, ItunesProvider, LastFmProvider,
    MusicBrainzProvider, urllib_fetcher)
from spotify_autoeq.modules.preset_mapper import PresetMapper, load_genre_map

from .config import Config

_LOG = logging.getLogger(__name__)


class UnavailableBackend:
    """Stands in when the real backend cannot even be constructed."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def apply(self, profile: EqProfile) -> None:
        raise BackendError(self._reason)

    def close(self) -> None:
        pass


def build_mapper(config: Config) -> PresetMapper:
    return PresetMapper(load_genre_map(), default_profile=config.mapper.default_profile,
                        podcast_profile=config.mapper.podcast_profile,
                        overrides=config.mapper.overrides)


def build_cache(config: Config) -> GenreCache:
    r = config.resolver
    return GenreCache(r.cache_path, positive_ttl_days=r.positive_ttl_days,
                      negative_ttl_days=r.negative_ttl_days)


def build_resolver(config: Config, cache: Optional[GenreCache] = None) -> GenreResolver:
    r = config.resolver
    common = dict(timeout_s=r.http_timeout_s, user_agent=r.user_agent)
    providers: list[GenreProvider] = []
    for name in r.providers:
        if name == "musicbrainz":
            providers.append(MusicBrainzProvider(urllib_fetcher, **common))
        elif name == "lastfm":
            providers.append(LastFmProvider(urllib_fetcher, r.lastfm_api_key, **common))
        elif name == "itunes":
            providers.append(ItunesProvider(urllib_fetcher, **common))
        elif name == "deezer":
            providers.append(DeezerProvider(urllib_fetcher, **common))
    return GenreResolver(providers, cache or build_cache(config))


def build_controller(config: Config, mapper: PresetMapper) -> EqController:
    profiles = builtin_profiles()
    for needed in (mapper.default_profile, mapper.podcast_profile):
        if needed not in profiles:
            raise ValueError(f"profile {needed!r} has no curve; known: {', '.join(sorted(profiles))}")
    unknown = sorted(p for p in mapper.profiles if p not in profiles)
    if unknown:
        _LOG.warning("mapping targets without a curve (will use default): %s", ", ".join(unknown))
    try:
        from spotify_autoeq.modules.eq_controller.gio_settings import GioSettingsWriter
        backend = PulseEffectsBackend(GioSettingsWriter())
    except BackendError as exc:
        _LOG.error("equalizer backend disabled: %s", exc)
        backend = UnavailableBackend(str(exc))
    return EqController(backend, profiles, default_profile=mapper.default_profile)
