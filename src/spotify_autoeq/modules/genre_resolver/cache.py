"""SQLite genre cache with separate positive and negative TTL."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

_SEPARATOR = "\n"
_DAY = 86400.0


@dataclass(frozen=True)
class CacheEntry:
    genres: tuple[str, ...]
    """Empty tuple is a cached negative result."""

    @property
    def negative(self) -> bool:
        return not self.genres


class GenreCache:
    def __init__(self, path: Union[str, Path], *, positive_ttl_days: float = 30.0,
                 negative_ttl_days: float = 1.0,
                 clock: Callable[[], float] = time.time) -> None:
        if positive_ttl_days <= 0 or negative_ttl_days <= 0:
            raise ValueError("TTL must be positive")
        self._pos = positive_ttl_days * _DAY
        self._neg = negative_ttl_days * _DAY
        self._clock = clock
        self._lock = threading.Lock()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS genres ("
                "artist TEXT PRIMARY KEY, genres TEXT NOT NULL, stored_at REAL NOT NULL)")

    def get(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            row = self._db.execute(
                "SELECT genres, stored_at FROM genres WHERE artist = ?", (key,)).fetchone()
        if row is None:
            return None
        genres = tuple(g for g in row[0].split(_SEPARATOR) if g)
        ttl = self._pos if genres else self._neg
        if self._clock() - row[1] >= ttl:
            return None
        return CacheEntry(genres)

    def put(self, key: str, genres: "tuple[str, ...]") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO genres(artist, genres, stored_at) VALUES (?, ?, ?)",
                (key, _SEPARATOR.join(genres), self._clock()))

    def purge_expired(self) -> int:
        now = self._clock()
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM genres WHERE (genres != '' AND ? - stored_at >= ?) "
                "OR (genres = '' AND ? - stored_at >= ?)", (now, self._pos, now, self._neg))
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
