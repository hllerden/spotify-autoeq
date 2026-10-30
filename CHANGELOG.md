# Changelog

## 1.1.0 - 2026-10-30

- Status file `$XDG_RUNTIME_DIR/spotify-autoeq/status.json` for panel
  indicators and scripts: current track, playback (playing, paused, idle,
  advertisement), genres and their source, applied profile with its band
  gains, and backend health. Documented in `docs/status-file.md`; disable with
  `status.enabled: false`.
- The genre cache remembers which provider supplied each entry; databases
  written by 1.0 are migrated automatically.
- Pause and resume are now reported to the status file (they still never
  trigger a lookup or an equalizer change).

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
