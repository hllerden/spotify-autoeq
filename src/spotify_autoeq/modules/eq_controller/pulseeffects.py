"""PulseEffects 4.8.4 backend driven through GSettings."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Callable, Optional, Sequence

from .ports import BackendError, EqProfile, SettingsWriter, SettingWrite
from .profiles import BAND_FREQUENCIES_HZ

_LOG = logging.getLogger(__name__)

EQ_SCHEMA = "com.github.wwmm.pulseeffects.equalizer"
CHANNEL_SCHEMA = "com.github.wwmm.pulseeffects.equalizer.channel"
EQ_PATH = "/com/github/wwmm/pulseeffects/sinkinputs/equalizer/"
APP_SCHEMA = "com.github.wwmm.pulseeffects"
APP_PATH = "/com/github/wwmm/pulseeffects/"
CHANNELS = ("leftchannel", "rightchannel")
BAND_Q = 1.41
MAX_GAIN_DB = 12.0


def build_writes(profile: EqProfile) -> list[SettingWrite]:
    """GSettings writes that realise ``profile`` (state is handled separately)."""
    if len(profile.gains_db) != len(BAND_FREQUENCIES_HZ):
        raise BackendError(f"profile {profile.name!r} needs {len(BAND_FREQUENCIES_HZ)} gains")
    if any(abs(g) > MAX_GAIN_DB for g in profile.gains_db):
        raise BackendError(f"profile {profile.name!r} exceeds +-{MAX_GAIN_DB} dB")
    # Pre-attenuate by the largest boost so the curve cannot clip.
    headroom = -max(0.0, *profile.gains_db)
    writes = [
        SettingWrite(EQ_SCHEMA, EQ_PATH, "num-bands", len(BAND_FREQUENCIES_HZ)),
        SettingWrite(EQ_SCHEMA, EQ_PATH, "split-channels", False),
        SettingWrite(EQ_SCHEMA, EQ_PATH, "input-gain", headroom),
    ]
    for channel in CHANNELS:
        path = f"{EQ_PATH}{channel}/"
        for i, (freq, gain) in enumerate(zip(BAND_FREQUENCIES_HZ, profile.gains_db)):
            writes += [
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-frequency", freq),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-gain", float(gain)),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-q", BAND_Q),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-type", "Bell"),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-mode", "RLC (BT)"),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-slope", "x1"),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-mute", False),
                SettingWrite(CHANNEL_SCHEMA, path, f"band{i}-solo", False),
            ]
    return writes


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=10,  # noqa: S603
                          check=False)


class PulseEffectsBackend:
    """Applies profiles to a running PulseEffects service.

    On the first apply global bypass is cleared and the equalizer ``state`` is
    toggled false -> true because PulseEffects may leave an already-enabled
    equalizer out of the pipeline. The service is started on demand and left
    running; ``shutdown_service`` is the explicit revert (``pulseeffects -q``).
    """

    def __init__(self, settings: SettingsWriter, *, binary: str = "pulseeffects",
                 runner: Runner = _run, sleep: Callable[[float], None] = time.sleep,
                 start_service: bool = True, settle_s: float = 1.5) -> None:
        self._settings = settings
        self._binary = binary
        self._run = runner
        self._sleep = sleep
        self._start_service = start_service
        self._settle = settle_s
        self._armed = False
        self._service: Optional["subprocess.Popen[bytes]"] = None

    def _service_running(self) -> bool:
        try:
            return self._run(["pgrep", "-x", "pulseeffects"]).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _ensure_service(self) -> None:
        if self._service_running():
            return
        if not self._start_service:
            raise BackendError("pulseeffects service is not running")
        try:
            self._service = subprocess.Popen(  # noqa: S603
                [self._binary, "--gapplication-service"], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise BackendError(f"cannot start {self._binary}: {exc}") from exc
        _LOG.info("started pulseeffects service")
        self._sleep(self._settle * 2)
        if not self._service_running():
            raise BackendError("pulseeffects exited right after start")
        self._armed = False

    def apply(self, profile: EqProfile) -> None:
        self._ensure_service()
        writes = build_writes(profile)
        if not self._armed:
            # Global bypass persists in dconf and silences every effect (measured
            # live: the curve only appeared after it was cleared).
            self._settings.write([SettingWrite(APP_SCHEMA, APP_PATH, "bypass", False),
                                  SettingWrite(EQ_SCHEMA, EQ_PATH, "state", False)])
            self._sleep(self._settle)
        self._settings.write(writes + [SettingWrite(EQ_SCHEMA, EQ_PATH, "state", True)])
        self._armed = True
        _LOG.debug("applied profile %s", profile.name)

    def shutdown_service(self) -> None:
        try:
            self._run([self._binary, "--quit"])
        except (OSError, subprocess.SubprocessError) as exc:
            _LOG.warning("pulseeffects --quit failed: %s", exc)
        self._armed = False

    def close(self) -> None:
        """Leaves the service running; use :meth:`shutdown_service` to revert."""
