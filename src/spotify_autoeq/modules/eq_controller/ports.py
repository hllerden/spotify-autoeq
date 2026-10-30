"""Ports of the equalizer controller module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class BackendError(Exception):
    """The equalizer backend is unavailable or rejected a command."""


@dataclass(frozen=True)
class EqProfile:
    """A named 10-band curve. ``gains_db`` is aligned with ``BAND_FREQUENCIES_HZ``."""

    name: str
    gains_db: tuple[float, ...]


class EqBackend(Protocol):
    def apply(self, profile: EqProfile) -> None:
        """Make ``profile`` audible. Raises :class:`BackendError` on failure."""

    def close(self) -> None:
        """Release resources; must not raise."""


@dataclass(frozen=True)
class SettingWrite:
    schema: str
    path: str
    key: str
    value: Any


class SettingsWriter(Protocol):
    """Transactional key/value store (GSettings in production)."""

    def write(self, batch: Sequence[SettingWrite]) -> None:
        """Apply all writes at once. Raises :class:`BackendError` on failure."""
