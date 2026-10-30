"""Genre equalizer curves generated in code (no preset files)."""

from __future__ import annotations

from .ports import EqProfile

BAND_FREQUENCIES_HZ: tuple[float, ...] = (
    31.25, 62.5, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0)

# dB per band: 31, 62, 125, 250, 500, 1k, 2k, 4k, 8k, 16k.
# Moderate curves: the target is a bluetooth headset on SBC, large boosts
# only add distortion.
_CURVES: dict[str, tuple[float, ...]] = {
    "Flat":       (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "Rock":       (4, 3, 2, 0, -1, -1, 1, 3, 4, 3),
    "Metal":      (3, 3, 1, -1, -2, -1, 2, 4, 3, 1),
    "Pop":        (-1, 0, 2, 3, 3, 2, 0, -1, -1, -1),
    "Electronic": (5, 4, 2, 0, -2, 0, 1, 2, 4, 4),
    "HipHop":     (6, 5, 3, 1, -1, -1, 1, 1, 2, 2),
    "RnB":        (4, 4, 2, 1, 0, -1, 0, 1, 2, 2),
    "Jazz":       (2, 2, 1, 1, -1, -1, 0, 1, 2, 3),
    "Classical":  (0, 0, 0, 0, 0, 0, -1, -1, 2, 3),
    "Acoustic":   (2, 2, 1, 1, 1, 1, 2, 2, 2, 1),
    "Podcast":    (-6, -4, -2, 0, 2, 3, 3, 1, -1, -2),
}


def builtin_profiles() -> dict[str, EqProfile]:
    return {name: EqProfile(name, tuple(float(g) for g in gains))
            for name, gains in _CURVES.items()}
