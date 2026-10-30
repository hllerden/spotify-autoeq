# Changelog

## 1.0.0 - 2026-10-30

First release.

- Follows Spotify track changes through MPRIS (`playerctl --follow`).
- Resolves artist genres from a SQLite cache and MusicBrainz, iTunes, Deezer
  (Last.fm optional).
- Maps genres to eleven equalizer profiles with a configurable keyword map and
  per-artist or per-track overrides.
- Applies 10-band curves to PulseEffects through GSettings, with automatic
  headroom and no commands when the profile is unchanged.
- Debounces rapid skips and drops lookups that finish after the song changed.
- Ignores advertisements, uses a podcast profile for episodes, returns to Flat
  when Spotify closes.
- Commands: `run`, `resolve`, `status`, `doctor`, `config init|path`,
  `service install|uninstall`; `SIGHUP` reloads the configuration.
- `doctor` checks Python, playerctl, PulseEffects, LV2 plugins, PyGObject, the
  sound server (PipeWire is reported as unsupported) and the configuration.
- Installable from PyPI with pipx or pip; the systemd user service is created
  by `spotify-autoeq service install`.
- Installer for source checkouts with two modes (command only, or service) and
  an uninstaller.
