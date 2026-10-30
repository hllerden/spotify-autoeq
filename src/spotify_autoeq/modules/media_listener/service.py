"""Spotify MPRIS listener built on ``playerctl --follow``.

The listener supervises one long-running ``playerctl`` process, parses each
metadata line it prints, drops repeated snapshots of the same track (pause,
play and seek produce new lines but the same identity) and hands new tracks to
an event sink. If ``playerctl`` exits it is restarted with exponential backoff.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Callable, Optional, Sequence

from .ports import EventSink, ManagedProcess, ProcessFactory, TrackEvent, TrackKind

_LOG = logging.getLogger(__name__)

FIELD_SEPARATOR = "\x1f"
"""ASCII unit separator; never appears in Spotify metadata."""

METADATA_FIELDS: tuple[str, ...] = (
    "mpris:trackid",
    "artist",
    "title",
    "album",
    "status",
)

_NO_TRACK_PATH = "/org/mpris/MediaPlayer2/TrackList/NoTrack"

_KIND_BY_SEGMENT = {
    "track": TrackKind.TRACK,
    "episode": TrackKind.EPISODE,
    "ad": TrackKind.AD,
    "local": TrackKind.LOCAL,
}


def build_format() -> str:
    """Return the ``playerctl --format`` template matching :data:`METADATA_FIELDS`."""
    return FIELD_SEPARATOR.join("{{%s}}" % field for field in METADATA_FIELDS)


def build_command(playerctl: str, player: str) -> list[str]:
    """Return the argv of the followed ``playerctl`` process."""
    return [
        playerctl,
        f"--player={player}",
        "--follow",
        "metadata",
        "--format",
        build_format(),
    ]


def classify_trackid(trackid: str) -> Optional[TrackKind]:
    """Classify a Spotify ``mpris:trackid``.

    Accepts both the D-Bus object path form ``/com/spotify/<kind>/<id>`` and the
    URI form ``spotify:<kind>:<id>``. Returns ``None`` when there is no track.
    """
    value = trackid.strip()
    if not value or value == _NO_TRACK_PATH:
        return None
    segment = ""
    if value.startswith("/com/spotify/"):
        parts = value.split("/")
        if len(parts) >= 4:
            segment = parts[3]
    elif value.startswith("spotify:"):
        parts = value.split(":")
        if len(parts) >= 3:
            segment = parts[1]
    return _KIND_BY_SEGMENT.get(segment.lower(), TrackKind.UNKNOWN)


def parse_metadata_line(line: str) -> Optional[TrackEvent]:
    """Parse one line printed by ``playerctl metadata --format``.

    Returns ``None`` for an empty line (player vanished) or a line without a
    usable trackid. Missing trailing fields are treated as empty strings.
    """
    text = line.rstrip("\r\n")
    if not text.strip():
        return None
    fields = text.split(FIELD_SEPARATOR)
    if len(fields) < len(METADATA_FIELDS):
        fields.extend([""] * (len(METADATA_FIELDS) - len(fields)))
    trackid, artist, title, album, status = (f.strip() for f in fields[: len(METADATA_FIELDS)])
    kind = classify_trackid(trackid)
    if kind is None:
        return None
    return TrackEvent(
        trackid=trackid,
        artist=artist,
        title=title,
        album=album,
        status=status,
        kind=kind,
    )


def _default_process_factory(argv: Sequence[str]) -> ManagedProcess:
    return subprocess.Popen(  # noqa: S603 - argv is fully controlled by this module
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


class PlayerctlListener:
    """Follows one MPRIS player through a supervised ``playerctl`` process."""

    def __init__(
        self,
        sink: EventSink,
        *,
        idle_sink: Optional[Callable[[], None]] = None,
        player: str = "spotify",
        playerctl: str = "playerctl",
        process_factory: Optional[ProcessFactory] = None,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        stable_after_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if initial_backoff_s <= 0 or max_backoff_s < initial_backoff_s:
            raise ValueError("backoff must satisfy 0 < initial <= max")
        self._sink = sink
        self._idle_sink = idle_sink
        self._argv = build_command(playerctl, player)
        self._factory: ProcessFactory = process_factory or _default_process_factory
        self._initial_backoff = initial_backoff_s
        self._max_backoff = max_backoff_s
        self._stable_after = stable_after_s
        self._clock = clock
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._process: Optional[ManagedProcess] = None
        self._thread: Optional[threading.Thread] = None
        self._last_identity: Optional[tuple[str, str, str]] = None

    @property
    def argv(self) -> list[str]:
        return list(self._argv)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("listener already started")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="media-listener", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._terminate_process(timeout)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                _LOG.warning("media listener thread did not stop within %.1f s", timeout)
        self._thread = None

    # -- supervision -------------------------------------------------------

    def _run(self) -> None:
        backoff = self._initial_backoff
        failure_streak = 0
        while not self._stop.is_set():
            started = self._clock()
            exit_code = self._run_once()
            if self._stop.is_set():
                break
            ran_for = self._clock() - started
            if ran_for >= self._stable_after:
                backoff = self._initial_backoff
                failure_streak = 0
            failure_streak += 1
            level = logging.WARNING if failure_streak == 1 else logging.DEBUG
            _LOG.log(
                level,
                "playerctl exited (code %s) after %.1f s; restarting in %.1f s",
                exit_code,
                ran_for,
                backoff,
            )
            self._notify_idle()
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2.0, self._max_backoff)
        _LOG.debug("media listener stopped")

    def _run_once(self) -> Optional[int]:
        try:
            process = self._factory(self._argv)
        except FileNotFoundError:
            _LOG.error("'%s' not found; install the playerctl package", self._argv[0])
            return None
        except OSError as exc:
            _LOG.error("cannot start playerctl: %s", exc)
            return None
        with self._lock:
            if self._stop.is_set():
                self._kill(process, 1.0)
                return None
            self._process = process
        _LOG.debug("started: %s", " ".join(self._argv[:-1]))
        try:
            stream = process.stdout
            if stream is None:
                _LOG.error("playerctl started without a stdout pipe")
                return None
            for line in stream:
                if self._stop.is_set():
                    break
                self._handle_line(line)
        except (OSError, ValueError) as exc:
            if not self._stop.is_set():
                _LOG.warning("reading playerctl output failed: %s", exc)
        finally:
            with self._lock:
                self._process = None
            code = self._kill(process, 2.0)
        return code

    def _handle_line(self, line: str) -> None:
        event = parse_metadata_line(line)
        if event is None:
            self._notify_idle()
            return
        if event.identity == self._last_identity:
            _LOG.debug("same track (%s), status %s", event.trackid, event.status)
            return
        self._last_identity = event.identity
        try:
            self._sink(event)
        except Exception:  # noqa: BLE001 - the listener must survive sink bugs
            _LOG.exception("track event sink failed")

    def _notify_idle(self) -> None:
        """Report the transition from "had a track" to "no track / player gone"."""
        if self._last_identity is None:
            return
        self._last_identity = None
        _LOG.debug("player has no track or disappeared")
        if self._idle_sink is None:
            return
        try:
            self._idle_sink()
        except Exception:  # noqa: BLE001 - the listener must survive sink bugs
            _LOG.exception("idle sink failed")

    def _terminate_process(self, timeout: float) -> None:
        with self._lock:
            process = self._process
        if process is not None:
            self._kill(process, timeout)

    @staticmethod
    def _kill(process: ManagedProcess, timeout: float) -> Optional[int]:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    return process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return process.wait(timeout=timeout)
            return process.poll()
        except OSError as exc:
            _LOG.debug("stopping playerctl failed: %s", exc)
            return None
        except subprocess.TimeoutExpired:
            _LOG.warning("playerctl did not exit after kill")
            return None
