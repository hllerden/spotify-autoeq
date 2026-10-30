"""End-to-end run of the real CLI with fake playerctl/pulseeffects/pgrep.

GSETTINGS_BACKEND=memory keeps every settings write inside the test process,
the cache is pre-seeded, so no network, no audio server and no user settings
are touched."""

import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from spotify_autoeq.apps.autoeq.doctor import schema_installed
from spotify_autoeq.modules.genre_resolver import GenreCache

pytestmark = pytest.mark.skipif(
    not schema_installed(), reason="PyGObject and the PulseEffects GSettings schema are required")

ROOT = Path(__file__).resolve().parents[1]
SEP = "\\x1f"


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def track(n, artist, status="Playing", kind="track"):
    return f"printf '/com/spotify/{kind}/{n}{SEP}{artist}{SEP}Song{n}{SEP}Al{SEP}{status}\\n'\n"


@pytest.fixture()
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "pgrep", "exit 0\n")
    script(bin_dir / "pulseeffects", "exit 0\n")
    cache = GenreCache(tmp_path / "g.sqlite3")
    cache.put("oasis", ("britpop", "rock"))
    cache.put("metallica", ("thrash metal",))
    cache.close()
    (tmp_path / "c.yaml").write_text(
        f"debounce_s: 0.05\nlogging: {{level: DEBUG}}\n"
        f"resolver: {{cache_path: {tmp_path / 'g.sqlite3'}}}\n")
    runtime = tmp_path / "run"
    runtime.mkdir()
    e = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GSETTINGS_BACKEND="memory",
             PYTHONPATH=str(ROOT / "src"), XDG_RUNTIME_DIR=str(runtime))
    return tmp_path, bin_dir, e


def run_daemon(tmp_path, e, seconds):
    proc = subprocess.Popen(
        [sys.executable, "-m", "spotify_autoeq.apps.autoeq", "-c", str(tmp_path / "c.yaml"), "run"],
        env=e, stderr=subprocess.PIPE, text=True)
    time.sleep(seconds)
    proc.send_signal(signal.SIGTERM)
    t0 = time.monotonic()
    err = proc.communicate(timeout=10)[1]
    return proc.returncode, time.monotonic() - t0, err


def test_track_change_pause_play_and_clean_shutdown(env):
    tmp, bin_dir, e = env
    script(bin_dir / "playerctl",
           track(1, "Oasis") + "sleep 0.4\n" + track(1, "Oasis", "Paused") + "sleep 0.2\n"
           + track(1, "Oasis") + "sleep 0.2\n" + track(2, "Metallica") + "exec sleep 60\n")
    code, took, err = run_daemon(tmp, e, 4.0)
    assert code == 0 and took < 5
    assert err.count("| profile=") == 2
    assert "profile=Rock" in err and "profile=Metal" in err
    assert "equalizer profile -> Rock" in err and "equalizer profile -> Metal" in err
    assert "same track" in err


def test_rapid_skips_apply_only_last_profile(env):
    tmp, bin_dir, e = env
    script(bin_dir / "playerctl",
           track(1, "Oasis") + track(2, "Metallica") + track(3, "Oasis", kind="track")
           + "exec sleep 60\n")
    code, _, err = run_daemon(tmp, e, 3.0)
    assert code == 0
    assert err.count("equalizer profile ->") == 1 and "equalizer profile -> Rock" in err


def test_service_survives_missing_pulseeffects_backend(env):
    tmp, bin_dir, e = env
    script(bin_dir / "pgrep", "exit 1\n")
    script(bin_dir / "pulseeffects", "exit 1\n")  # starts and dies at once
    script(bin_dir / "playerctl", track(1, "Oasis") + "exec sleep 60\n")
    code, _, err = run_daemon(tmp, e, 4.0)
    assert code == 0
    assert "profile=Rock" in err and "equalizer backend unavailable" in err


def test_sighup_reload_keeps_running(env):
    tmp, bin_dir, e = env
    script(bin_dir / "playerctl", "exec sleep 60\n")
    proc = subprocess.Popen(
        [sys.executable, "-m", "spotify_autoeq.apps.autoeq", "-c", str(tmp / "c.yaml"), "run"],
        env=e, stderr=subprocess.PIPE, text=True)
    time.sleep(1.5)
    proc.send_signal(signal.SIGHUP)
    time.sleep(1.5)
    (tmp / "c.yaml").write_text("bogus: 1\n")
    proc.send_signal(signal.SIGHUP)
    time.sleep(1.5)
    assert proc.poll() is None
    proc.send_signal(signal.SIGTERM)
    err = proc.communicate(timeout=10)[1]
    assert "configuration reloaded" in err and "reload failed" in err
    assert proc.returncode == 0


def test_invalid_config_exits_with_code_2(tmp_path):
    (tmp_path / "bad.yaml").write_text("bogus: 1\n")
    r = subprocess.run([sys.executable, "-m", "spotify_autoeq.apps.autoeq", "-c",
                        str(tmp_path / "bad.yaml"), "status"],
                       env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                       capture_output=True, text=True)
    assert r.returncode == 2 and "unknown key" in r.stderr


def test_spotify_closing_returns_to_flat(env):
    tmp, bin_dir, e = env
    script(bin_dir / "playerctl", track(1, "Oasis") + "sleep 0.6\nprintf '\\n'\nexec sleep 60\n")
    code, _, err = run_daemon(tmp, e, 4.0)
    assert code == 0
    assert "equalizer profile -> Rock" in err
    assert "no track playing -> Flat" in err and "equalizer profile -> Flat" in err


def test_status_file_follows_pause_and_shutdown(env):
    import json
    tmp, bin_dir, e = env
    status_file = tmp / "run" / "spotify-autoeq" / "status.json"
    script(bin_dir / "playerctl",
           track(1, "Oasis") + "sleep 1.2\n" + track(1, "Oasis", "Paused") + "exec sleep 60\n")
    proc = subprocess.Popen(
        [sys.executable, "-m", "spotify_autoeq.apps.autoeq", "-c", str(tmp / "c.yaml"), "run"],
        env=e, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 8
    seen = None
    while time.monotonic() < deadline:
        if status_file.exists():
            doc = json.loads(status_file.read_text())
            if doc["profile"]["name"] == "Rock" and doc["playback"] == "paused":
                seen = doc
                break
        time.sleep(0.1)
    assert seen is not None, "status file never showed a paused Rock track"
    assert seen["genres"][0] == "britpop"
    assert seen["genre_source"] == "cache" and seen["genre_cached"] is True
    assert seen["daemon"]["pid"] == proc.pid
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=10)
    assert json.loads(status_file.read_text())["daemon"]["state"] == "stopped"
