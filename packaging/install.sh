#!/usr/bin/env bash
# Installer for a source checkout (for a released version use pipx or pip, see
# the README). Per user: never needs root and never touches system directories
# or the sound server configuration.
#
#   packaging/install.sh cli                 command only: run it yourself from a terminal
#   packaging/install.sh service             command + systemd user service (starts at login)
#   packaging/install.sh uninstall           remove program, link and service; keep config/cache
#   packaging/install.sh uninstall --purge   also remove configuration and cache
#
# Re-running "cli" or "service" upgrades an existing installation.
# Overrides for dry runs: HOME, PREFIX, BIN_DIR, UNIT_DIR, NO_SYSTEMCTL=1.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local/share/spotify-autoeq}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/spotify-autoeq"
CACHE_DIR="$HOME/.cache/spotify-autoeq"
APP="$PREFIX/venv/bin/spotify-autoeq"

service_flags=()
[ -n "${UNIT_DIR:-}" ] && service_flags+=(--unit-dir "$UNIT_DIR")
[ "${NO_SYSTEMCTL:-0}" = 1 ] && service_flags+=(--no-systemctl)

usage() { sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
die() { echo "error: $*" >&2; exit 1; }

install_program() {
    command -v python3 >/dev/null || die "python3 is not installed"
    # --system-site-packages: PyGObject (gi) and PyYAML come from the distribution.
    python3 -m venv --system-site-packages "$PREFIX/venv"
    "$PREFIX/venv/bin/pip" install --quiet --upgrade pip
    # Build from a copy so no build/ or egg-info directories appear in the source tree.
    WORK="$(mktemp -d)"
    trap 'rm -rf "${WORK:-}"' EXIT
    cp -r "$SRC/pyproject.toml" "$SRC/README.md" "$SRC/LICENSE" "$SRC/src" "$WORK/"
    "$PREFIX/venv/bin/pip" install --quiet --force-reinstall --no-deps "$WORK"

    mkdir -p "$BIN_DIR"
    ln -sf "$APP" "$BIN_DIR/spotify-autoeq"
    "$APP" config init >/dev/null 2>&1 || true   # keeps an existing file
    "$APP" doctor || echo "warning: fix the items above before starting (see README)" >&2
}

path_hint() {
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) echo "note: $BIN_DIR is not in PATH; log out and in again, or add it to your shell profile." ;;
    esac
}

cmd_cli() {
    install_program
    echo "installed the command: $BIN_DIR/spotify-autoeq"
    echo "start it with:  spotify-autoeq run     (Ctrl+C stops it)"
    path_hint
}

cmd_service() {
    install_program
    "$APP" service install "${service_flags[@]}"
    path_hint
}

cmd_uninstall() {
    local purge=0
    [ "${1:-}" = "--purge" ] && purge=1
    if [ -x "$APP" ]; then
        "$APP" service uninstall "${service_flags[@]}" || true
    fi
    [ -L "$BIN_DIR/spotify-autoeq" ] && rm -f "$BIN_DIR/spotify-autoeq"
    rm -rf "$PREFIX"
    if [ "$purge" = 1 ]; then
        rm -rf "$CONFIG_DIR" "$CACHE_DIR"
        echo "removed the program, the service, the configuration and the cache."
    else
        echo "removed the program and the service. Kept: $CONFIG_DIR and $CACHE_DIR"
        echo "(use 'uninstall --purge' to remove them as well)"
    fi
}

case "${1:-}" in
    cli) cmd_cli ;;
    service) cmd_service ;;
    uninstall) shift; cmd_uninstall "$@" ;;
    -h|--help|"") usage ;;
    *) usage >&2; exit 1 ;;
esac
