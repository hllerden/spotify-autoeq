"""Follow the track playing in an MPRIS player (Spotify) via ``playerctl``."""

from .ports import EventSink, ManagedProcess, MediaListener, ProcessFactory, TrackEvent, TrackKind
from .service import (
    FIELD_SEPARATOR,
    METADATA_FIELDS,
    PlayerctlListener,
    build_command,
    build_format,
    classify_trackid,
    parse_metadata_line,
)

__all__ = [
    "EventSink",
    "FIELD_SEPARATOR",
    "METADATA_FIELDS",
    "ManagedProcess",
    "MediaListener",
    "PlayerctlListener",
    "ProcessFactory",
    "TrackEvent",
    "TrackKind",
    "build_command",
    "build_format",
    "classify_trackid",
    "parse_metadata_line",
]
