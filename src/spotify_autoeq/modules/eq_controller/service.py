"""Equalizer controller: profile bookkeeping on top of a backend."""

from __future__ import annotations

import logging
import threading
from typing import Mapping, Optional

from .ports import BackendError, EqBackend, EqProfile

_LOG = logging.getLogger(__name__)


class EqController:
    """Applies named profiles; never raises for backend problems."""

    def __init__(self, backend: EqBackend, profiles: Mapping[str, EqProfile],
                 *, default_profile: str = "Flat") -> None:
        if default_profile not in profiles:
            raise ValueError(f"default profile {default_profile!r} is not defined")
        self._backend = backend
        self._profiles = dict(profiles)
        self._default = default_profile
        self._active: Optional[str] = None
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def active_profile(self) -> Optional[str]:
        return self._active

    @property
    def last_error(self) -> Optional[str]:
        """Message of the last failed apply; ``None`` after a success."""
        return self._last_error

    def has_profile(self, name: str) -> bool:
        return name in self._profiles

    def gains(self, name: str) -> "tuple[float, ...]":
        """Band gains of ``name`` (empty for an unknown profile)."""
        profile = self._profiles.get(name)
        return profile.gains_db if profile is not None else ()

    def set_profile(self, name: str) -> bool:
        """Apply ``name``. Returns True when the backend was commanded and succeeded.

        Same-as-active is a no-op (False). Unknown names fall back to the default
        profile. A failed apply leaves ``active_profile`` unchanged so the next
        request retries."""
        if name not in self._profiles:
            _LOG.warning("unknown profile %r; using %s", name, self._default)
            name = self._default
        with self._lock:
            if name == self._active:
                _LOG.debug("profile %s already active", name)
                return False
            try:
                self._backend.apply(self._profiles[name])
            except BackendError as exc:
                _LOG.error("equalizer backend unavailable: %s", exc)
                self._last_error = str(exc)
                return False
            except Exception as exc:  # noqa: BLE001 - the daemon must survive backend bugs
                _LOG.exception("equalizer backend raised unexpectedly")
                self._last_error = f"{type(exc).__name__}: {exc}"
                return False
            self._last_error = None
            self._active = name
            _LOG.info("equalizer profile -> %s", name)
            return True

    def close(self) -> None:
        try:
            self._backend.close()
        except Exception:  # noqa: BLE001
            _LOG.exception("closing equalizer backend failed")
