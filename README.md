# spotify-autoeq

[Türkçe README](README.tr.md)

Automatically switches your Linux equalizer to match the genre of the song
playing in Spotify. Rock gets more bass and sparkle, podcasts get clearer
voices, and everything returns to flat when Spotify closes.

![spotify-autoeq running in a terminal](docs/assets/demo.gif)

Version 1.0.0. Linux, PulseAudio, PulseEffects 4.8.

## How it works

1. `playerctl --follow` reports Spotify track changes through MPRIS. There is
   no polling; the service only wakes up when the song changes.
2. After a short debounce (1.5 s, so skipping through songs does not trigger
   anything), the artist's genres are looked up: local SQLite cache first, then
   MusicBrainz, iTunes and Deezer (Last.fm if you configure a key).
3. The genres vote for one of eleven profiles using a keyword map
   (`genre_map.yaml`, easy to edit). Earlier genres weigh more.
4. The profile's 10-band curve is written to PulseEffects through GSettings.
   If the profile is already active, nothing is sent.

```mermaid
flowchart LR
    A[Spotify] -- MPRIS --> B[playerctl --follow]
    B --> C[debounce and dedupe]
    C --> D[genre cache / MusicBrainz / iTunes / Deezer]
    D --> E[genre to profile vote]
    E --> F[PulseEffects equalizer]
```

Behaviour you can rely on:

- Pause, resume and seeking never trigger a lookup or an equalizer change.
- Skipping quickly through songs applies only the profile of the last one.
  A lookup that finishes after the song changed is discarded.
- Advertisements leave the equalizer untouched; podcast episodes use the
  Podcast profile.
- When Spotify closes, the equalizer returns to Flat.
- If PulseEffects is not available the service logs the error and keeps
  running; it retries on the next song.
- The equalizer lowers the input gain by the largest boost of the curve so
  boosted profiles do not clip.

## Profiles

![Equalizer profiles](docs/assets/profiles.svg)

Flat, Rock, Metal, Pop, Electronic, HipHop, RnB, Jazz, Classical, Acoustic and
Podcast. The curves are intentionally moderate; they are tuned for Bluetooth
headphones, where large boosts only add distortion.

## Requirements and supported systems

| System | Status |
|---|---|
| Ubuntu 22.04 LTS (PulseAudio, PulseEffects 4.8.4, Python 3.10) | Tested |
| Ubuntu-based distributions on the 22.04 base (Linux Mint 21 and similar) | Expected to work, not tested |
| Ubuntu 24.04 LTS | Not tested. The package exists (PulseEffects 4.8.7) but the default sound server is PipeWire, which is not supported; it can only work if you run real PulseAudio |
| Ubuntu 20.04 and older | Not supported (Python older than 3.10) |

You need:

- PulseAudio as the sound server (`spotify-autoeq doctor` tells you if you are on PipeWire)
- PulseEffects 4.8.x, `playerctl`, `lsp-plugins-lv2` (the equalizer engine used
  by PulseEffects), `python3-gi`, `python3-yaml`
- Python 3.10 or newer
- The Spotify desktop client (any packaging that exposes the MPRIS name `spotify`)

```
sudo apt install --no-install-recommends pulseeffects playerctl lsp-plugins-lv2 python3-gi python3-yaml
```

## Install

Installation is per user: it never needs root and never touches system
directories or the sound server configuration. Check your system at any time
with `spotify-autoeq doctor`.

### Recommended: pipx

```
sudo apt install pipx
pipx install --system-site-packages spotify-autoeq
pipx ensurepath          # first time only, then open a new terminal
spotify-autoeq doctor
```

`--system-site-packages` is required so the program can use the system's
PyGObject (`python3-gi`). Without pipx, a plain virtual environment works too:

```
python3 -m venv --system-site-packages ~/.local/share/spotify-autoeq
~/.local/share/spotify-autoeq/bin/pip install spotify-autoeq
```

### From a source checkout

```
git clone <repository-url> spotify-autoeq
cd spotify-autoeq
packaging/install.sh cli        # or: packaging/install.sh service
```

### Choose how it runs

**A. Run it yourself in a terminal.** Nothing runs in the background and nothing
starts at login. Good for trying it out.

```
spotify-autoeq run              # Ctrl+C stops it
```

**B. Install it as a service and forget about it.** A systemd user service starts
at every login and restarts itself if it ever fails.

```
spotify-autoeq service install
journalctl --user -u spotify-autoeq -f          # live log
systemctl --user stop spotify-autoeq            # stop for this session
spotify-autoeq service uninstall                # remove the service again
```

(With a source checkout, `packaging/install.sh service` does the install and
this step in one go.) Stopping the service runs `pulseeffects --quit`, which
sends the audio streams straight back to your output device.

### Upgrade

```
pipx upgrade spotify-autoeq
systemctl --user restart spotify-autoeq         # only if you use the service
```

From a checkout: pull and run `packaging/install.sh` with the same mode again.

## Uninstall

```
spotify-autoeq service uninstall                # if you installed the service
pipx uninstall spotify-autoeq                   # or: packaging/install.sh uninstall
rm -r ~/.config/spotify-autoeq ~/.cache/spotify-autoeq    # optional: settings and genre cache
```

The program never changes your PulseEffects settings files beyond the
equalizer values it writes while running, so there is nothing else to undo. To
remove the packages themselves:

```
sudo apt remove pulseeffects playerctl lsp-plugins-lv2
```

`packaging/install.sh uninstall --purge` removes everything of a checkout
install, including settings and cache.

## Commands

```
spotify-autoeq run                       # follow Spotify in the foreground
spotify-autoeq resolve "Oasis" "Wonderwall"   # show genres and the chosen profile
spotify-autoeq status                    # current track, cache entry, PulseEffects state
spotify-autoeq doctor                    # check every requirement, with fix hints
spotify-autoeq config init               # write a commented config file to edit
spotify-autoeq service install|uninstall # manage the systemd user service
spotify-autoeq --version
```

`SIGHUP` reloads the
configuration without a restart; `SIGTERM` or `Ctrl+C` shuts down cleanly.

## Configuration

Optional file: `~/.config/spotify-autoeq/config.yaml`
(`spotify-autoeq config init` writes
[a commented example](src/spotify_autoeq/apps/autoeq/data/config.example.yaml) with every key).

| Key | Default | Meaning |
|---|---|---|
| `player` | `spotify` | MPRIS player name |
| `debounce_s` | `1.5` | Wait after a song change before looking it up |
| `logging.level` | `INFO` | `DEBUG` shows every skipped duplicate and cache hit |
| `resolver.providers` | `musicbrainz, itunes, deezer` | Lookup order; `lastfm` needs `lastfm_api_key` |
| `resolver.http_timeout_s` | `4.0` | Per-request timeout |
| `resolver.positive_ttl_days` / `negative_ttl_days` | `30` / `1` | Cache lifetime of found / not found results |
| `mapper.default_profile` | `Flat` | Used when no genre matches |
| `mapper.overrides` | none | `"artist"` or `"artist - title"` mapped to a profile |

Example override:

```yaml
mapper:
  overrides:
    "Sezen Aksu": Acoustic
    "Daft Punk - Veridis Quo": Classical
```

To change which genre keywords select which profile, edit
`src/spotify_autoeq/modules/preset_mapper/genre_map.yaml` and reinstall.

## Privacy

To find a genre, the artist name (and for iTunes and Deezer also the song
title) is sent to MusicBrainz, iTunes and Deezer. Results are cached locally in
`~/.cache/spotify-autoeq/genres.sqlite3`, so each artist is looked up about once
a month. Nothing else leaves your machine, and no account or token is needed.

## Limitations

- PulseEffects has not been maintained since 2020. This project targets its
  4.8.4 release and PulseAudio. On PipeWire use EasyEffects instead; it is not
  supported here.
- PulseEffects processes every application's audio, not only Spotify.
- Changing the profile can cause a very brief click while the filters are
  rebuilt.
- Genre data comes from public databases and is sometimes coarse or wrong for
  small artists; use `mapper.overrides` to correct it.
- Only Spotify is followed.

## Development

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

The test suite needs no network: providers use recorded JSON responses, and the
end-to-end tests run the real command line against fake `playerctl` and
`pulseeffects` executables with `GSETTINGS_BACKEND=memory`, so your audio
setup and settings are never touched.

Run from a checkout without installing:

```
PYTHONPATH=src .venv/bin/python -m spotify_autoeq.apps.autoeq run
```

The images in this README are produced by `docs/make_assets.py` (the terminal
animation is a replay of the log in `docs/assets/session.log`, captured from a
real session).

Layout:

```
src/spotify_autoeq/
  modules/media_listener/   playerctl supervisor, track events
  modules/genre_resolver/   cache and online providers
  modules/preset_mapper/    genre to profile vote
  modules/eq_controller/    profiles and the PulseEffects backend
  apps/autoeq/              configuration, daemon, command line, doctor, service unit
packaging/                  installer for source checkouts
```

## License

MIT, see [LICENSE](LICENSE). Changes are listed in [CHANGELOG.md](CHANGELOG.md).
