"""Command line entry point: run | resolve | status."""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import threading
from importlib import resources
from pathlib import Path
from typing import Optional, Sequence

from spotify_autoeq import __version__
from spotify_autoeq.modules.genre_resolver import normalize_artist
from spotify_autoeq.modules.media_listener import PlayerctlListener

from . import doctor, systemd_unit
from .config import Config, ConfigError, default_config_path, load_config
from .daemon import AutoEqDaemon
from .log import configure_logging
from .runtime import build_cache, build_controller, build_mapper, build_resolver

_LOG = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spotify-autoeq", description=__doc__)
    p.add_argument("-c", "--config", type=Path, help="configuration file")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="follow Spotify and switch the equalizer")
    r = sub.add_parser("resolve", help="show genres and profile for a track")
    r.add_argument("artist")
    r.add_argument("title", nargs="?", default="")
    sub.add_parser("status", help="show the current track and environment")
    sub.add_parser("doctor", help="check that every requirement is in place")
    c = sub.add_parser("config", help="configuration file helpers")
    c.add_argument("action", choices=["init", "path"],
                   help="init: write a commented example file; path: print its location")
    c.add_argument("--force", action="store_true", help="overwrite an existing file (init)")
    sv = sub.add_parser("service", help="manage the systemd user service")
    sv.add_argument("action", choices=["install", "uninstall"])
    sv.add_argument("--unit-dir", type=Path, help=argparse.SUPPRESS)
    sv.add_argument("--no-systemctl", action="store_true", help=argparse.SUPPRESS)
    return p


def _load(path: Optional[Path]) -> Config:
    config = load_config(path)
    configure_logging(config.logging.level, config.logging.journal)
    return config


def cmd_resolve(config: Config, artist: str, title: str) -> int:
    mapper = build_mapper(config)
    genres = build_resolver(config).resolve(artist, title)
    print(f"genres:  {', '.join(genres) if genres else '-'}")
    print(f"profile: {mapper.profile_for(artist, title, genres)}")
    return 0


def _playerctl(config: Config, *args: str) -> str:
    try:
        out = subprocess.run(["playerctl", f"--player={config.player}", *args],
                             capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def cmd_status(config: Config, config_path: Optional[Path]) -> int:
    path = config_path or default_config_path()
    print(f"config:  {path} ({'found' if path.exists() else 'defaults'})")
    artist = _playerctl(config, "metadata", "artist")
    title = _playerctl(config, "metadata", "title")
    state = _playerctl(config, "status")
    print(f"spotify: {state or 'not running'}" + (f" - {artist} - {title}" if title else ""))
    if artist:
        cache = build_cache(config)
        entry = cache.get(normalize_artist(artist))
        mapper = build_mapper(config)
        if entry is None:
            print("cache:   no entry")
        else:
            print(f"cache:   {', '.join(entry.genres) or '(negative)'}")
            print(f"profile: {mapper.profile_for(artist, title, entry.genres)}")
    running = subprocess.run(["pgrep", "-x", "pulseeffects"], capture_output=True,
                             check=False).returncode == 0
    print(f"pulseeffects: {'running' if running else 'not running'}")
    return 0


def cmd_run(config: Config, config_path: Optional[Path]) -> int:
    for check in doctor.run_checks(config_path, include_player=False):
        if not check.ok and check.required:
            _LOG.warning("requirement not met - %s: %s (%s)", check.name, check.detail, check.hint)
    cache = build_cache(config)
    mapper = build_mapper(config)
    controller = build_controller(config, mapper)
    daemon = AutoEqDaemon(build_resolver(config, cache), mapper, controller,
                          debounce_s=config.debounce_s)
    listener = PlayerctlListener(daemon.on_event, idle_sink=daemon.on_idle, player=config.player)
    stop = threading.Event()
    reload_request = threading.Event()

    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGHUP, lambda *_: reload_request.set())

    daemon.start()
    listener.start()
    _LOG.info("spotify-autoeq started (player=%s)", config.player)
    try:
        while not stop.wait(0.5):
            if reload_request.is_set():
                reload_request.clear()
                try:
                    new = load_config(config_path)
                    daemon.reconfigure(build_mapper(new), new.debounce_s)
                    configure_logging(new.logging.level, new.logging.journal)
                    _LOG.info("configuration reloaded")
                except (ConfigError, ValueError) as exc:
                    _LOG.error("reload failed, keeping previous configuration: %s", exc)
    finally:
        _LOG.info("shutting down")
        listener.stop()
        daemon.stop()
        controller.close()
        cache.close()
    return 0


def cmd_doctor(config_path: Optional[Path]) -> int:
    checks = doctor.run_checks(config_path)
    print(doctor.format_report(checks))
    ok = doctor.all_required_ok(checks)
    print("\nall requirements are met" if ok else "\nsome requirements are missing")
    return 0 if ok else 1


def cmd_config(action: str, force: bool, config_path: Optional[Path]) -> int:
    target = config_path or default_config_path()
    if action == "path":
        print(target)
        return 0
    if target.exists() and not force:
        print(f"{target} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    example = resources.files("spotify_autoeq.apps.autoeq").joinpath(
        "data", "config.example.yaml").read_text(encoding="utf-8")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(example, encoding="utf-8")
    except OSError as exc:
        print(f"cannot write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {target}")
    return 0


def cmd_service(args: argparse.Namespace) -> int:
    use_systemctl = not args.no_systemctl
    try:
        if args.action == "install":
            path = systemd_unit.install(unit_dir=args.unit_dir, use_systemctl=use_systemctl)
            print(f"installed {path}")
            if use_systemctl:
                print("service started; it will also start at every login")
                print("logs: journalctl --user -u spotify-autoeq -f")
        else:
            removed = systemd_unit.uninstall(unit_dir=args.unit_dir, use_systemctl=use_systemctl)
            print("service removed" if removed else "service was not installed")
    except systemd_unit.ServiceError as exc:
        print(f"spotify-autoeq: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        return cmd_doctor(args.config)
    if args.command == "config":
        return cmd_config(args.action, args.force, args.config)
    if args.command == "service":
        return cmd_service(args)
    try:
        config = _load(args.config)
    except ConfigError as exc:
        print(f"spotify-autoeq: {exc}", file=sys.stderr)
        return 2
    if args.command == "run":
        return cmd_run(config, args.config)
    if args.command == "resolve":
        return cmd_resolve(config, args.artist, args.title)
    return cmd_status(config, args.config)


if __name__ == "__main__":
    sys.exit(main())
