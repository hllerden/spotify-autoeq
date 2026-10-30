# Status file

While it runs, `spotify-autoeq` keeps one small JSON file up to date so that
panel indicators, scripts and other front ends can show what it is doing
without talking to the daemon. It is rewritten only when something changes (no
polling) and replaced atomically, so a reader never sees a half-written file.

- Location: `$XDG_RUNTIME_DIR/spotify-autoeq/status.json`
  (usually `/run/user/1000/spotify-autoeq/status.json`). The file lives in
  memory-backed storage and disappears at logout.
- Configuration: the `status` section (`enabled`, `path`) of the config file.
- Stability: this format is a public contract. Fields are only ever added;
  when a field changes meaning or is removed, `schema_version` is raised.
  Readers should ignore fields they do not know and show a hint when
  `schema_version` is higher than the one they were written for.

## Example

```json
{
  "schema_version": 1,
  "updated_at": 1793343600.4,
  "daemon": { "state": "running", "pid": 4242, "version": "1.1.0" },
  "playback": "playing",
  "track": { "artist": "Placebo", "title": "This Picture", "kind": "track" },
  "genres": ["alternative rock", "indie rock", "rock"],
  "genre_source": "musicbrainz",
  "genre_cached": false,
  "profile": {
    "name": "Rock",
    "applied_at": 1793343598.1,
    "gains_db": [4, 3, 2, 0, -1, -1, 1, 3, 4, 3],
    "in_effect": true
  },
  "backend": { "name": "pulseeffects", "ok": true, "last_error": null }
}
```

## Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Format version, currently `1` |
| `updated_at` | number | Unix time of the last write |
| `daemon.state` | `"running"` or `"stopped"` | `stopped` is written on a clean shutdown. After a crash the file still says `running`: check that `daemon.pid` is alive (for example that `/proc/<pid>` exists) |
| `daemon.pid`, `daemon.version` | integer, string | Process id and program version |
| `playback` | `"playing"`, `"paused"`, `"idle"`, `"advertisement"` | `idle` means Spotify is closed or has no track |
| `track` | object or `null` | `artist`, `title`, and `kind` (`track`, `episode`, `ad`, `local`, `unknown`) |
| `genres` | list of strings | Genres found for the artist; empty while the lookup runs or when none was found |
| `genre_source` | string or `null` | Where the genres came from: `musicbrainz`, `itunes`, `deezer`, `lastfm`, `cache` (older cache entry), `none` (nothing found) |
| `genre_cached` | boolean | `true` when the answer came from the local cache |
| `profile.name` | string or `null` | Last profile that was applied; `null` before the first one |
| `profile.applied_at` | number or `null` | Unix time when that profile became active |
| `profile.gains_db` | list of numbers | Ten band gains in dB for 31.25 Hz to 16 kHz; empty before the first profile |
| `profile.in_effect` | boolean | `false` while the backend is failing: the profile shown is the last known one but is not being heard |
| `backend.name` | string | Equalizer backend, `pulseeffects` |
| `backend.ok` | boolean | Whether the last attempt to talk to the backend succeeded |
| `backend.last_error` | string or `null` | Message of the last failure |

## Reading it from a shell

```
cat "$XDG_RUNTIME_DIR/spotify-autoeq/status.json"
python3 -m json.tool "$XDG_RUNTIME_DIR/spotify-autoeq/status.json"
inotifywait -m -e moved_to "$XDG_RUNTIME_DIR/spotify-autoeq/"    # react to every change
```

Because the file is replaced by renaming, watch the directory (or use
`Gio.FileMonitor` on the file, which reports the replacement).
