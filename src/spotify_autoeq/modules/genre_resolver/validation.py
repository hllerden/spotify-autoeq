"""Normalisation and sanity checks applied to provider answers."""

from __future__ import annotations

import re
import unicodedata

_USELESS = frozenset({
    "music", "musica", "muzik", "müzik", "other", "others", "unknown", "various",
    "general", "misc", "miscellaneous", "audio", "songs", "single", "soundtrack",
    "seen live", "favorites", "favourites", "favoritos", "british", "uk", "usa",
    "american", "england", "turkish", "turkce", "türkçe", "turk", "türk", "turkey", "greek",
    "french", "german", "spanish", "italian", "japanese", "korean", "swedish", "canadian", "male vocalists", "female vocalists", "under 2000 listeners",
})
_FEAT = re.compile(r"\s*[\(\[]?\b(feat|ft|featuring)\b\.?.*$", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def fold(text: str) -> str:
    """Case- and accent-insensitive form used for comparisons and cache keys."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD.sub(" ", stripped.replace("&", " and ")).strip()


def normalize_artist(artist: str) -> str:
    """Cache key: folded primary artist without featuring credits."""
    return fold(_FEAT.sub("", artist))


_CREDIT_SPLIT = re.compile(r"\s*(?:,|;|&|/|\band\b|\bx\b|\bwith\b|\bvs\.?)\s*", re.IGNORECASE)


def _credits(name: str) -> "set[str]":
    return {fold(p) for p in _CREDIT_SPLIT.split(_FEAT.sub("", name)) if fold(p)}


def artists_match(wanted: str, found: str) -> bool:
    """True when ``found`` is the same artist as ``wanted``.

    Exact folded match, or the primary name equals one of the credited names
    of the other side (``Calvin Harris`` vs ``Calvin Harris, Rihanna``).
    Substring matches are rejected so a namesake's genre is never accepted."""
    a, b = normalize_artist(wanted), normalize_artist(found)
    if not a or not b:
        return False
    return a == b or a in _credits(found) or b in _credits(wanted)


def is_useful_genre(genre: str) -> bool:
    """False for empty, numeric or non-descriptive tags such as ``music``."""
    g = fold(genre)
    if len(g) < 2 or g.isdigit():
        return False
    return g not in _USELESS


def clean_genres(raw: "list[str]", limit: int = 5) -> "tuple[str, ...]":
    """Drop useless tags and duplicates, keep order, cap at ``limit``."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        key = fold(item)
        if key in seen or not is_useful_genre(item):
            continue
        seen.add(key)
        out.append(item.strip())
        if len(out) >= limit:
            break
    return tuple(out)
