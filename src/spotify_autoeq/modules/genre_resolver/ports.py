"""Ports of the genre resolver module."""

from __future__ import annotations

from typing import Callable, Mapping, Optional, Protocol, Sequence


class ProviderError(Exception):
    """A provider could not be queried (network, HTTP status, bad payload)."""


Fetcher = Callable[[str, Mapping[str, str], float], str]
"""``fetcher(url, headers, timeout_s)`` returns the response body as text.

Raises :class:`ProviderError` on any failure."""


class GenreProvider(Protocol):
    """One online source of genre information."""

    name: str

    def lookup(self, artist: str, title: str) -> Optional[Sequence[str]]:
        """Return raw genre names, or ``None`` when the source has no answer.

        Raises :class:`ProviderError` when the source could not be reached."""
