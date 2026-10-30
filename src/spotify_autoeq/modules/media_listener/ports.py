"""Data types and ports of the media listener module."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import IO, Callable, Optional, Protocol, Sequence


class TrackKind(enum.Enum):
    """Kind of the item Spotify is playing, derived from ``mpris:trackid``."""

    TRACK = "track"
    EPISODE = "episode"
    AD = "ad"
    LOCAL = "local"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TrackEvent:
    """One metadata snapshot of the followed player."""

    trackid: str
    artist: str
    title: str
    album: str
    status: str
    kind: TrackKind

    @property
    def identity(self) -> tuple[str, str, str]:
        """Key used for de-duplication.

        Playback status is intentionally excluded so that pause/play never
        produces a new identity. Artist and title are included because Spotify
        may publish a trackid before the rest of the metadata is filled in.
        """
        return (self.trackid, self.artist, self.title)

    @property
    def display(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.artist or self.trackid


EventSink = Callable[[TrackEvent], None]


class MediaListener(Protocol):
    """Produces :class:`TrackEvent` objects for the followed player."""

    def start(self) -> None:
        """Start following the player in a background thread."""

    def stop(self, timeout: float = 5.0) -> None:
        """Stop following and release all resources."""


class ManagedProcess(Protocol):
    """Subset of :class:`subprocess.Popen` used by the listener."""

    stdout: Optional[IO[str]]

    def poll(self) -> Optional[int]: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: Optional[float] = None) -> int: ...


ProcessFactory = Callable[[Sequence[str]], ManagedProcess]
"""Starts a process with text-mode, line-buffered stdout."""
