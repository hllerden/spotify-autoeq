"""Resolve the genre of a track's artist from cache and online providers."""

from .cache import CacheEntry, GenreCache
from .http import urllib_fetcher
from .ports import Fetcher, GenreProvider, ProviderError
from .providers import DeezerProvider, ItunesProvider, LastFmProvider, MusicBrainzProvider
from .service import GenreResolver, Resolution
from .validation import artists_match, clean_genres, is_useful_genre, normalize_artist

__all__ = [
    "CacheEntry", "DeezerProvider", "Fetcher", "GenreCache", "GenreProvider", "GenreResolver",
    "ItunesProvider", "LastFmProvider", "MusicBrainzProvider", "ProviderError", "Resolution",
    "artists_match",
    "clean_genres", "is_useful_genre", "normalize_artist", "urllib_fetcher",
]
