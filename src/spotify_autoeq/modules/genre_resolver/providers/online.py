"""MusicBrainz, Last.fm, iTunes and Deezer genre providers."""

from __future__ import annotations

from typing import Any, Optional, Sequence
from urllib.parse import quote, urlencode

from ..ports import Fetcher, ProviderError
from ..validation import artists_match
from .base import JsonProvider, RateLimiter


def _dicts(value: Any) -> "list[dict[str, Any]]":
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


class MusicBrainzProvider(JsonProvider):
    """Artist tags, ordered by vote count. Limited to 1 request per second."""

    name = "musicbrainz"
    _URL = "https://musicbrainz.org/ws/2/artist/"

    def __init__(self, fetcher: Fetcher, **kw: Any) -> None:
        kw.setdefault("limiter", RateLimiter(1.1))
        super().__init__(fetcher, **kw)

    def lookup(self, artist: str, title: str) -> Optional[Sequence[str]]:
        query = urlencode({"query": 'artist:"%s"' % artist.replace('"', " "),
                           "fmt": "json", "limit": 5})
        data = self._get_json(f"{self._URL}?{query}")
        for item in _dicts(data.get("artists") if isinstance(data, dict) else None):
            if not artists_match(artist, str(item.get("name", ""))):
                continue
            tags = [t for t in _dicts(item.get("tags")) if isinstance(t.get("count"), int)]
            tags.sort(key=lambda t: t["count"], reverse=True)
            names = [str(t.get("name", "")) for t in tags if t["count"] > 0]
            if names:
                return names
        return None


class LastFmProvider(JsonProvider):
    name = "lastfm"
    _URL = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, fetcher: Fetcher, api_key: str, **kw: Any) -> None:
        if not api_key:
            raise ValueError("Last.fm API key required")
        kw.setdefault("limiter", RateLimiter(0.25))
        super().__init__(fetcher, **kw)
        self._key = api_key

    def lookup(self, artist: str, title: str) -> Optional[Sequence[str]]:
        query = urlencode({"method": "artist.gettoptags", "artist": artist, "autocorrect": 1,
                           "api_key": self._key, "format": "json"})
        data = self._get_json(f"{self._URL}?{query}")
        if isinstance(data, dict) and "error" in data:
            raise ProviderError(f"lastfm error {data.get('error')}: {data.get('message')}")
        tags = data.get("toptags", {}).get("tag") if isinstance(data, dict) else None
        names = [str(t.get("name", "")) for t in _dicts(tags)
                 if isinstance(t.get("count"), (int, float)) and t["count"] >= 20]
        return names or None


class ItunesProvider(JsonProvider):
    name = "itunes"
    _URL = "https://itunes.apple.com/search"

    def __init__(self, fetcher: Fetcher, **kw: Any) -> None:
        kw.setdefault("limiter", RateLimiter(3.0))
        super().__init__(fetcher, **kw)

    def lookup(self, artist: str, title: str) -> Optional[Sequence[str]]:
        query = urlencode({"term": f"{artist} {title}", "entity": "song", "limit": 5})
        data = self._get_json(f"{self._URL}?{query}")
        results = _dicts(data.get("results") if isinstance(data, dict) else None)
        names = [str(r["primaryGenreName"]) for r in results
                 if r.get("primaryGenreName") and artists_match(artist, str(r.get("artistName", "")))]
        return names or None


class DeezerProvider(JsonProvider):
    """Track search, then the genres of the matching album (two requests)."""

    name = "deezer"
    _BASE = "https://api.deezer.com"

    def __init__(self, fetcher: Fetcher, **kw: Any) -> None:
        kw.setdefault("limiter", RateLimiter(0.2))
        super().__init__(fetcher, **kw)

    def lookup(self, artist: str, title: str) -> Optional[Sequence[str]]:
        query = urlencode({"q": f"{artist} {title}", "limit": 5})
        data = self._get_json(f"{self._BASE}/search?{query}")
        for hit in _dicts(data.get("data") if isinstance(data, dict) else None):
            who = hit.get("artist")
            album = hit.get("album")
            if not (isinstance(who, dict) and isinstance(album, dict)):
                continue
            if not artists_match(artist, str(who.get("name", ""))) or not album.get("id"):
                continue
            detail = self._get_json(f"{self._BASE}/album/{quote(str(album['id']), safe='')}")
            genres = detail.get("genres", {}).get("data") if isinstance(detail, dict) else None
            names = [str(g.get("name", "")) for g in _dicts(genres)]
            if names:
                return names
        return None
