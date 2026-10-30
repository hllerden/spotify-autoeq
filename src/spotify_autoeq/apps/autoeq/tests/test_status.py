import json
import threading
import time

import pytest

from spotify_autoeq.apps.autoeq.config import ConfigError, parse_config
from spotify_autoeq.apps.autoeq.daemon import AutoEqDaemon
from spotify_autoeq.apps.autoeq.status import (
    SCHEMA_VERSION, StatusPublisher, default_status_path)
from spotify_autoeq.modules.genre_resolver import Resolution
from spotify_autoeq.modules.media_listener import TrackEvent, TrackKind
from spotify_autoeq.modules.preset_mapper import PresetMapper, load_genre_map


def ev(n=1, kind=TrackKind.TRACK, status="Playing"):
    return TrackEvent(f"/com/spotify/track/{n}", f"artist{n}", f"title{n}", "", status, kind)


@pytest.fixture()
def pub(tmp_path):
    now = [1000.0]
    p = StatusPublisher(tmp_path / "run" / "status.json", version="9.9", pid=42,
                        clock=lambda: now[0])
    p.now = now
    p.file = tmp_path / "run" / "status.json"
    return p


def read(p):
    return json.loads(p.file.read_text(encoding="utf-8"))


def test_initial_document_is_valid_and_complete(pub):
    d = read(pub)
    assert d["schema_version"] == SCHEMA_VERSION == 1
    assert d["daemon"] == {"state": "running", "pid": 42, "version": "9.9"}
    assert d["playback"] == "idle" and d["track"] is None and d["genres"] == []
    assert d["profile"]["name"] is None and d["backend"]["ok"] is True


def test_track_then_resolution_then_profile(pub):
    pub.set_track(ev(1))
    d = read(pub)
    assert d["playback"] == "playing" and d["track"]["artist"] == "artist1"
    assert d["genres"] == []                       # cleared while the lookup runs
    pub.set_resolution(["rock", "indie"], "musicbrainz", True)
    pub.now[0] = 1005.0
    pub.set_profile("Rock", [1.0] * 10)
    d = read(pub)
    assert d["genres"] == ["rock", "indie"] and d["genre_source"] == "musicbrainz"
    assert d["genre_cached"] is True
    assert d["profile"] == {"name": "Rock", "applied_at": 1005.0,
                            "gains_db": [1.0] * 10, "in_effect": True}


def test_applied_at_changes_only_when_the_profile_changes(pub):
    pub.now[0] = 1.0
    pub.set_profile("Rock", [0.0] * 10)
    pub.now[0] = 2.0
    pub.set_profile("Rock", [0.0] * 10)
    assert read(pub)["profile"]["applied_at"] == 1.0
    pub.now[0] = 3.0
    pub.set_profile("Pop", [0.0] * 10)
    assert read(pub)["profile"]["applied_at"] == 3.0


def test_pause_resume_idle_and_advertisement(pub):
    pub.set_track(ev(1))
    pub.set_playback("Paused")
    assert read(pub)["playback"] == "paused"
    pub.set_playback("Playing")
    assert read(pub)["playback"] == "playing"
    pub.set_resolution(["rock"], "itunes", False)
    pub.set_track(ev(2, TrackKind.AD))
    d = read(pub)
    assert d["playback"] == "advertisement" and d["genres"] == ["rock"]   # kept
    pub.set_playback("Paused")
    assert read(pub)["playback"] == "advertisement"
    pub.set_idle()
    d = read(pub)
    assert d["playback"] == "idle" and d["track"] is None and d["genres"] == []


def test_backend_error_marks_profile_not_in_effect(pub):
    pub.set_profile("Rock", [0.0] * 10)
    pub.set_backend("PulseEffects: boom")
    d = read(pub)
    assert d["backend"] == {"name": "pulseeffects", "ok": False, "last_error": "PulseEffects: boom"}
    assert d["profile"]["in_effect"] is False and d["profile"]["name"] == "Rock"
    pub.set_backend(None)
    d = read(pub)
    assert d["backend"]["ok"] is True and d["profile"]["in_effect"] is True


def test_stop_marks_daemon_stopped(pub):
    pub.set_track(ev(1))
    pub.stop()
    d = read(pub)
    assert d["daemon"]["state"] == "stopped" and d["playback"] == "idle"


def test_write_is_atomic_and_leaves_no_temp_file(pub):
    for i in range(20):
        pub.set_resolution([f"g{i}"], "x", False)
        json.loads(pub.file.read_text())            # never a partial document
    assert [p.name for p in pub.file.parent.iterdir()] == ["status.json"]


def test_unwritable_location_does_not_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    p = StatusPublisher(blocker / "sub" / "status.json", version="1")
    p.set_idle()
    p.stop()


def test_default_path_uses_xdg_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_status_path() == tmp_path / "spotify-autoeq" / "status.json"


class Resolver:
    def __init__(self, gate=None):
        self.gate = gate

    def resolve_detailed(self, artist, title):
        if self.gate and artist in self.gate:
            self.gate[artist].wait(5)
        return Resolution(("rock",) if artist != "artist9" else (), "musicbrainz", False)


class Controller:
    def __init__(self):
        self.last_error, self.active_profile, self.fail = None, None, False

    def set_profile(self, name):
        if self.fail:
            self.last_error = "backend down"
            return False
        self.last_error, self.active_profile = None, name
        return True

    def gains(self, name):
        return (2.0,) * 10


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def make(pub, resolver=None, controller=None):
    d = AutoEqDaemon(resolver or Resolver(), PresetMapper(load_genre_map()),
                     controller or Controller(), debounce_s=0.05, status=pub)
    d.start()
    return d


def test_daemon_publishes_full_flow(pub):
    d = make(pub)
    d.on_event(ev(1))
    assert wait_for(lambda: read(pub)["profile"]["name"] == "Rock")
    doc = read(pub)
    assert doc["genres"] == ["rock"] and doc["genre_source"] == "musicbrainz"
    assert doc["profile"]["gains_db"] == [2.0] * 10 and doc["backend"]["ok"] is True
    d.on_status(ev(1, status="Paused"))
    assert read(pub)["playback"] == "paused"
    d.on_idle()
    doc = read(pub)
    assert doc["playback"] == "idle" and doc["profile"]["name"] == "Flat"
    d.stop()
    assert read(pub)["daemon"]["state"] == "stopped"


def test_daemon_podcast_and_ad(pub):
    d = make(pub)
    d.on_event(ev(1, TrackKind.EPISODE))
    doc = read(pub)
    assert doc["profile"]["name"] == "Podcast" and doc["genre_source"] == "none"
    d.on_event(ev(2, TrackKind.AD))
    doc = read(pub)
    assert doc["playback"] == "advertisement" and doc["profile"]["name"] == "Podcast"
    d.stop()


def test_daemon_reports_backend_failure(pub):
    ctrl = Controller()
    ctrl.fail = True
    d = make(pub, controller=ctrl)
    d.on_event(ev(1))
    assert wait_for(lambda: read(pub)["backend"]["ok"] is False)
    doc = read(pub)
    assert doc["backend"]["last_error"] == "backend down" and doc["profile"]["name"] is None
    d.stop()


def test_stale_lookup_is_not_published(pub):
    gate = {"artist1": threading.Event()}
    d = make(pub, Resolver(gate))
    d.on_event(ev(1))
    time.sleep(0.2)
    d.on_event(ev(9))                    # skipped; artist9 has no genres
    gate["artist1"].set()                # the late answer for artist1 arrives now
    assert wait_for(lambda: read(pub)["profile"]["name"] == "Flat")
    time.sleep(0.2)
    doc = read(pub)
    assert doc["track"]["artist"] == "artist9" and doc["genres"] == []
    assert doc["profile"]["name"] == "Flat"
    d.stop()


def test_config_status_section():
    assert parse_config({}).status.enabled is True and parse_config({}).status.path is None
    cfg = parse_config({"status": {"enabled": False, "path": "~/s.json"}})
    assert cfg.status.enabled is False and cfg.status.path.name == "s.json"
    with pytest.raises(ConfigError):
        parse_config({"status": {"enabled": "yes"}})
    with pytest.raises(ConfigError):
        parse_config({"status": {"extra": 1}})
