"""Machine-readable status file for front ends (panel indicators, scripts).

The daemon rewrites one small JSON document whenever something changes; there
is no polling. The document is replaced atomically, so a reader never sees a
partial file. The format is a public contract, see docs/status-file.md.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from spotify_autoeq.modules.media_listener import TrackEvent, TrackKind

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def default_status_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "spotify-autoeq" / "status.json"


class NullStatus:
    """Used when the status file is disabled."""

    def set_track(self, event: TrackEvent) -> None: ...
    def set_playback(self, status: str) -> None: ...
    def set_idle(self) -> None: ...
    def set_resolution(self, genres: Sequence[str], source: str, cached: bool) -> None: ...
    def set_profile(self, name: str, gains_db: Sequence[float]) -> None: ...
    def set_backend(self, error: Optional[str]) -> None: ...
    def stop(self) -> None: ...


class StatusPublisher(NullStatus):
    """Keeps the current state and writes it to ``path`` after every change."""

    def __init__(self, path: Path, *, version: str, backend: str = "pulseeffects",
                 pid: Optional[int] = None, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._warned = False
        self._state: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": 0.0,
            "daemon": {"state": "running", "pid": pid if pid is not None else os.getpid(),
                       "version": version},
            "playback": "idle",
            "track": None,
            "genres": [],
            "genre_source": None,
            "genre_cached": False,
            "profile": {"name": None, "applied_at": None, "gains_db": [], "in_effect": True},
            "backend": {"name": backend, "ok": True, "last_error": None},
        }
        self._publish()

    # -- updates ---------------------------------------------------------

    def set_track(self, event: TrackEvent) -> None:
        with self._lock:
            ad = event.kind is TrackKind.AD
            self._state["playback"] = "advertisement" if ad else _playback(event.status)
            self._state["track"] = {"artist": event.artist, "title": event.title,
                                    "kind": event.kind.value}
            if not ad:  # the equalizer stays as it was during an advertisement
                self._state["genres"] = []
                self._state["genre_source"] = None
                self._state["genre_cached"] = False
            self._publish()

    def set_playback(self, status: str) -> None:
        with self._lock:
            if self._state["playback"] != "advertisement":
                self._state["playback"] = _playback(status)
            self._publish()

    def set_idle(self) -> None:
        with self._lock:
            self._state["playback"] = "idle"
            self._state["track"] = None
            self._state["genres"] = []
            self._state["genre_source"] = None
            self._state["genre_cached"] = False
            self._publish()

    def set_resolution(self, genres: Sequence[str], source: str, cached: bool) -> None:
        with self._lock:
            self._state["genres"] = list(genres)
            self._state["genre_source"] = source or "cache"
            self._state["genre_cached"] = cached
            self._publish()

    def set_profile(self, name: str, gains_db: Sequence[float]) -> None:
        with self._lock:
            profile = self._state["profile"]
            if profile["name"] != name:
                profile["applied_at"] = self._clock()
            profile["name"] = name
            profile["gains_db"] = [float(g) for g in gains_db]
            self._publish()

    def set_backend(self, error: Optional[str]) -> None:
        with self._lock:
            self._state["backend"]["ok"] = error is None
            self._state["backend"]["last_error"] = error
            self._state["profile"]["in_effect"] = error is None
            self._publish()

    def stop(self) -> None:
        with self._lock:
            self._state["daemon"]["state"] = "stopped"
            self._state["playback"] = "idle"
            self._publish()

    # -- output ------------------------------------------------------------

    def snapshot(self) -> "dict[str, Any]":
        with self._lock:
            return json.loads(json.dumps(self._state))

    def _publish(self) -> None:
        self._state["updated_at"] = self._clock()
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            if not self._warned:
                self._warned = True
                _LOG.warning("cannot write the status file %s: %s", self._path, exc)


def _playback(status: str) -> str:
    return "paused" if status.strip().lower() == "paused" else "playing"
