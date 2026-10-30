"""Environment checks behind ``spotify-autoeq doctor``."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from spotify_autoeq.modules.eq_controller.pulseeffects import EQ_SCHEMA

from .config import ConfigError, load_config

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]

_LV2_DIRS = ("/usr/lib/lv2", "/usr/lib64/lv2", "/usr/local/lib/lv2", "~/.lv2")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    required: bool = True


def _run(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=5,  # noqa: S603
                          check=False)


def schema_installed(schema: str = EQ_SCHEMA) -> Optional[bool]:
    """True/False for the GSettings schema, ``None`` when PyGObject is missing."""
    try:
        import gi  # type: ignore[import-not-found]
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # type: ignore[import-not-found]
    except (ImportError, ValueError):
        return None
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(schema, True) is not None


def _sound_server(runner: Runner, which: Callable[[str], Optional[str]]) -> Check:
    if which("pactl") is None:
        return Check("sound server", False, "pactl not found",
                     "sudo apt install pulseaudio-utils")
    try:
        out = runner(["pactl", "info"]).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("sound server", False, f"pactl info failed: {exc}",
                     "is the sound server running?")
    name = next((line.split(":", 1)[1].strip() for line in out.splitlines()
                 if line.startswith("Server Name:")), "")
    if not name:
        return Check("sound server", False, "no answer from the sound server",
                     "is the sound server running?")
    if "pipewire" in name.lower():
        return Check("sound server", False, name,
                     "PipeWire is not supported; use EasyEffects, or switch to PulseAudio")
    return Check("sound server", True, name)


def run_checks(config_path: Optional[Path] = None, *, runner: Runner = _run,
               which: Callable[[str], Optional[str]] = shutil.which,
               schema_probe: Callable[[], Optional[bool]] = schema_installed,
               lv2_dirs: Sequence[str] = _LV2_DIRS, include_player: bool = True) -> "list[Check]":
    checks = [Check("python", sys.version_info >= (3, 10), sys.version.split()[0],
                    "Python 3.10 or newer is required")]
    for binary, package in (("playerctl", "playerctl"), ("pulseeffects", "pulseeffects")):
        found = which(binary)
        checks.append(Check(binary, found is not None, found or "not found",
                            f"sudo apt install {package}"))
    lv2 = any((Path(d).expanduser() / "lsp-plugins.lv2").is_dir() for d in lv2_dirs)
    checks.append(Check("LSP equalizer plugins", lv2, "found" if lv2 else "not found",
                        "sudo apt install lsp-plugins-lv2"))
    schema = schema_probe()
    if schema is None:
        checks.append(Check("PyGObject (gi)", False, "not importable",
                            "sudo apt install python3-gi; with pipx use --system-site-packages"))
    else:
        checks.append(Check("PulseEffects settings", schema,
                            "schema found" if schema else "schema missing",
                            "sudo apt install pulseeffects"))
    checks.append(_sound_server(runner, which))
    try:
        load_config(config_path)
        checks.append(Check("configuration", True, "valid"))
    except ConfigError as exc:
        checks.append(Check("configuration", False, str(exc), "fix or remove the file"))
    if include_player and which("playerctl") is not None:
        try:
            players = runner(["playerctl", "-l"]).stdout.split()
        except (OSError, subprocess.SubprocessError):
            players = []
        running = "spotify" in players
        checks.append(Check("Spotify", running, "running" if running else "not running",
                            "start Spotify; this check is informational", required=False))
    return checks


def format_report(checks: Sequence[Check]) -> str:
    lines = []
    for c in checks:
        mark = "ok  " if c.ok else ("warn" if not c.required else "FAIL")
        lines.append(f"[{mark}] {c.name}: {c.detail}")
        if not c.ok and c.hint:
            lines.append(f"       -> {c.hint}")
    return "\n".join(lines)


def all_required_ok(checks: Sequence[Check]) -> bool:
    return all(c.ok or not c.required for c in checks)
