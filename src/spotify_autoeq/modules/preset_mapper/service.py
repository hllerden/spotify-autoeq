"""Genre -> equalizer profile mapping."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Union

import yaml

from ..genre_resolver.validation import fold

_LOG = logging.getLogger(__name__)
DEFAULT_MAP_PATH = Path(__file__).with_name("genre_map.yaml")


def load_genre_map(path: Union[str, Path, None] = None) -> "dict[str, list[str]]":
    """Load ``profile -> [keyword, ...]`` from YAML (default: bundled map)."""
    target = Path(path) if path else DEFAULT_MAP_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(f"{target}: expected a non-empty mapping of profile -> keywords")
    result: dict[str, list[str]] = {}
    for profile, words in raw.items():
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise ValueError(f"{target}: '{profile}' must map to a list of strings")
        result[str(profile)] = list(words)
    return result


class PresetMapper:
    """Maps genres of a track to the name of an equalizer profile."""

    def __init__(self, genre_map: Mapping[str, Iterable[str]], *, default_profile: str = "Flat",
                 podcast_profile: str = "Podcast",
                 overrides: Optional[Mapping[str, str]] = None) -> None:
        self.default_profile = default_profile
        self.podcast_profile = podcast_profile
        self._overrides = {fold(k): v for k, v in (overrides or {}).items()}
        self._keywords: dict[str, str] = {}
        for profile, words in genre_map.items():
            for word in words:
                key = fold(word)
                if key and self._keywords.setdefault(key, profile) != profile:
                    _LOG.warning("keyword %r is mapped to several profiles; keeping %s",
                                 word, self._keywords[key])
        # Longest keyword first so that the most specific one wins.
        self._by_length = sorted(self._keywords, key=len, reverse=True)

    @property
    def profiles(self) -> "set[str]":
        return set(self._keywords.values()) | {self.default_profile, self.podcast_profile}

    def match_genre(self, genre: str) -> Optional[str]:
        """Profile of one genre: exact keyword, else longest contained keyword."""
        key = fold(genre)
        if not key:
            return None
        if key in self._keywords:
            return self._keywords[key]
        padded = f" {key} "
        for word in self._by_length:
            if f" {word} " in padded:
                return self._keywords[word]
        for word in self._by_length:  # compound words: "synthpop", "hardrock"
            if len(word) >= 4 and word in key:
                return self._keywords[word]
        return None

    def map_genres(self, genres: Sequence[str]) -> str:
        """Weighted vote; earlier genres weigh more, ties go to the earliest."""
        scores: dict[str, int] = {}
        first_seen: dict[str, int] = {}
        total = len(genres)
        for index, genre in enumerate(genres):
            profile = self.match_genre(genre)
            if profile is None:
                continue
            scores[profile] = scores.get(profile, 0) + (total - index)
            first_seen.setdefault(profile, index)
        if not scores:
            return self.default_profile
        return min(scores, key=lambda p: (-scores[p], first_seen[p]))

    def override_for(self, artist: str, title: str) -> Optional[str]:
        """User rule: ``"artist - title"`` first, then ``artist``."""
        return (self._overrides.get(fold(f"{artist} - {title}"))
                or self._overrides.get(fold(artist)))

    def profile_for(self, artist: str, title: str, genres: Sequence[str]) -> str:
        return self.override_for(artist, title) or self.map_genres(genres)
