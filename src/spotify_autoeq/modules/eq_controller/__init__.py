"""Equalizer control: profiles and the PulseEffects backend."""

from .ports import BackendError, EqBackend, EqProfile, SettingsWriter, SettingWrite
from .profiles import BAND_FREQUENCIES_HZ, builtin_profiles
from .pulseeffects import PulseEffectsBackend, build_writes
from .service import EqController

__all__ = [
    "BAND_FREQUENCIES_HZ", "BackendError", "EqBackend", "EqController", "EqProfile",
    "PulseEffectsBackend", "SettingWrite", "SettingsWriter", "build_writes", "builtin_profiles",
]
