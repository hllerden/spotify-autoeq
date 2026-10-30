"""Orchestration: track events -> genre -> profile -> equalizer."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

from spotify_autoeq.modules.media_listener import TrackEvent, TrackKind

from .status import NullStatus

_LOG = logging.getLogger(__name__)


class Resolution(Protocol):
    genres: Sequence[str]
    source: str
    cached: bool


class Resolver(Protocol):
    def resolve_detailed(self, artist: str, title: str) -> Resolution: ...


class Mapper(Protocol):
    podcast_profile: str
    default_profile: str

    def profile_for(self, artist: str, title: str, genres: Sequence[str]) -> str: ...


class Controller(Protocol):
    last_error: Optional[str]
    active_profile: Optional[str]

    def set_profile(self, name: str) -> bool: ...
    def gains(self, name: str) -> Sequence[float]: ...


@dataclass
class _Pending:
    generation: int
    event: TrackEvent
    due: float


class AutoEqDaemon:
    """Receives track events on the listener thread and does the slow work on a
    worker thread.

    Every event bumps a generation counter. The worker re-checks it after the
    (possibly slow) genre lookup, so a late answer for a skipped song is never
    applied. Events inside the debounce window replace each other."""

    def __init__(self, resolver: Resolver, mapper: Mapper, controller: Controller,
                 *, debounce_s: float = 1.5, status: Optional[NullStatus] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._resolver = resolver
        self._mapper = mapper
        self._controller = controller
        self._status = status or NullStatus()
        self._debounce = debounce_s
        self._clock = clock
        self._cond = threading.Condition()
        self._generation = 0
        self._pending: Optional[_Pending] = None
        self._stopping = False
        self._thread: Optional[threading.Thread] = None

    # -- configuration reload -------------------------------------------------

    def reconfigure(self, mapper: Mapper, debounce_s: float) -> None:
        with self._cond:
            self._mapper = mapper
            self._debounce = debounce_s

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("daemon already started")
        self._thread = threading.Thread(target=self._worker, name="autoeq-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._cond:
            self._stopping = True
            self._generation += 1
            self._pending = None
            self._cond.notify_all()
        self._status.stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None

    # -- event entry point (listener thread; never blocks) ----------------------

    def on_event(self, event: TrackEvent) -> None:
        with self._cond:
            self._generation += 1
            generation = self._generation
            self._status.set_track(event)
            if event.kind is TrackKind.AD:
                _LOG.info("advertisement; equalizer left untouched")
                self._pending = None
                return
            if event.kind is TrackKind.EPISODE:
                self._pending = None
                profile = self._mapper.podcast_profile
                self._status.set_resolution((), "none", False)
                _LOG.info("episode %s -> %s", event.display, profile)
            else:
                profile = None
                self._pending = _Pending(generation, event, self._clock() + self._debounce)
                self._cond.notify_all()
                _LOG.debug("track queued: %s", event.display)
        if profile is not None:
            self._apply_if_current(generation, profile)

    def on_status(self, event: TrackEvent) -> None:
        """Pause/resume of the same track: only the status file changes."""
        self._status.set_playback(event.status)

    def on_idle(self) -> None:
        """Player closed or stopped: cancel pending work and return to the default."""
        with self._cond:
            self._generation += 1
            generation = self._generation
            self._pending = None
            profile = self._mapper.default_profile
            self._status.set_idle()
        _LOG.info("no track playing -> %s", profile)
        self._apply_if_current(generation, profile)

    # -- worker -------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            with self._cond:
                while not self._stopping:
                    pending = self._pending
                    if pending is None:
                        self._cond.wait()
                        continue
                    remaining = pending.due - self._clock()
                    if remaining <= 0:
                        self._pending = None
                        break
                    self._cond.wait(remaining)
                else:
                    return
            try:
                self._process(pending)
            except Exception:  # noqa: BLE001 - one bad track must not end the worker
                _LOG.exception("processing %s failed", pending.event.display)

    def _process(self, pending: _Pending) -> None:
        event = pending.event
        resolution = self._resolver.resolve_detailed(event.artist, event.title)
        genres = list(resolution.genres)
        with self._cond:
            mapper = self._mapper
            if pending.generation == self._generation:
                self._status.set_resolution(genres, resolution.source, resolution.cached)
        profile = mapper.profile_for(event.artist, event.title, genres)
        _LOG.info("%s | genres=%s | profile=%s", event.display,
                  ", ".join(genres) or "-", profile)
        self._apply_if_current(pending.generation, profile)

    def _apply_if_current(self, generation: int, profile: str) -> None:
        with self._cond:
            if generation != self._generation:
                _LOG.info("dropping stale result (profile %s)", profile)
                return
        self._controller.set_profile(profile)
        error = self._controller.last_error
        applied = self._controller.active_profile or profile
        if error is None:
            self._status.set_profile(applied, self._controller.gains(applied))
        self._status.set_backend(error)
