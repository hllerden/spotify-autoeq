# Contributing

Bug reports and pull requests are welcome.

## Reporting a problem

Run `spotify-autoeq doctor` and include its output, your distribution and
version, and the relevant lines of `journalctl --user -u spotify-autoeq`
(set `logging.level: DEBUG` in the configuration for more detail).

## Development setup

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

The tests need no network and never touch your audio setup. They do need the
`python3-gi` package and, for the end-to-end tests, the PulseEffects package
(for its settings schema); those tests are skipped when it is missing.

## Guidelines

- Keep modules independent: the pieces under `src/spotify_autoeq/modules/`
  communicate through the small ports defined in each module.
- Add a test for every behaviour change. Network access in tests goes through
  the injectable fetcher with recorded responses.
- Use conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, ...).
- Genre keywords live in `src/spotify_autoeq/modules/preset_mapper/genre_map.yaml`;
  improving them is a good first contribution.
