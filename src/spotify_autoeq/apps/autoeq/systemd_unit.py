"""Install and remove the systemd user service."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Callable, Optional, Sequence

UNIT_NAME = "spotify-autoeq.service"
_PLACEHOLDER = "@EXEC_START@"

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class ServiceError(Exception):
    """The service could not be installed or removed."""


def default_unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _quote(arg: str) -> str:
    """Quote one ExecStart word the way systemd expects."""
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    if escaped == arg and not any(c in arg for c in " \t'"):
        return arg
    return f'"{escaped}"'


def exec_start(python: str) -> str:
    """Command line of the service: this interpreter running the package.

    Using the interpreter that is running right now keeps the service working
    for pipx, virtual environments and --user installs alike."""
    return " ".join(_quote(p) for p in (python, "-m", "spotify_autoeq.apps.autoeq", "run"))


def render_unit(python: str) -> str:
    template = resources.files("spotify_autoeq.apps.autoeq").joinpath(
        "data", UNIT_NAME).read_text(encoding="utf-8")
    return template.replace(_PLACEHOLDER, exec_start(python))


def _run(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=30,  # noqa: S603
                          check=False)


def _systemctl(runner: Runner, *args: str, check: bool = True) -> None:
    result = runner(["systemctl", "--user", *args])
    if check and result.returncode != 0:
        raise ServiceError(f"systemctl --user {' '.join(args)} failed: "
                           f"{(result.stderr or result.stdout).strip()}")


def install(*, unit_dir: Optional[Path] = None, python: str = sys.executable,
            runner: Runner = _run, use_systemctl: bool = True) -> Path:
    """Write the unit, then enable and start it."""
    target_dir = unit_dir or default_unit_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / UNIT_NAME
        path.write_text(render_unit(python), encoding="utf-8")
    except OSError as exc:
        raise ServiceError(f"cannot write the unit file: {exc}") from exc
    if use_systemctl:
        _systemctl(runner, "daemon-reload")
        _systemctl(runner, "enable", UNIT_NAME)
        _systemctl(runner, "restart", UNIT_NAME)
    return path


def uninstall(*, unit_dir: Optional[Path] = None, runner: Runner = _run,
              use_systemctl: bool = True) -> bool:
    """Stop, disable and delete the unit. Returns False if it was not installed."""
    path = (unit_dir or default_unit_dir()) / UNIT_NAME
    if use_systemctl:
        _systemctl(runner, "disable", "--now", UNIT_NAME, check=False)
    existed = path.exists()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise ServiceError(f"cannot remove {path}: {exc}") from exc
    if use_systemctl:
        _systemctl(runner, "daemon-reload", check=False)
    return existed
