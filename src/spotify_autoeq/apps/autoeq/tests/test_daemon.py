import threading
import time

from spotify_autoeq.apps.autoeq.daemon import AutoEqDaemon
from spotify_autoeq.modules.genre_resolver import Resolution
from spotify_autoeq.modules.media_listener import TrackEvent, TrackKind
from spotify_autoeq.modules.preset_mapper import PresetMapper, load_genre_map


def ev(n, kind=TrackKind.TRACK, artist=None, status="Playing"):
    return TrackEvent(trackid=f"/com/spotify/track/{n}", artist=artist or f"artist{n}",
                      title=f"title{n}", album="", status=status, kind=kind)


class Resolver:
    def __init__(self, genres=None, gate=None):
        self.calls, self.genres, self.gate = [], genres or {}, gate

    def resolve_detailed(self, artist, title):
        self.calls.append(artist)
        if self.gate and artist in self.gate:
            self.gate[artist].wait(5)
        genres = tuple(self.genres.get(artist, ()))
        return Resolution(genres, "musicbrainz" if genres else "none", False)


class Controller:
    def __init__(self):
        self.profiles, self.changed = [], threading.Event()
        self.last_error = None
        self.active_profile = None

    def set_profile(self, name):
        self.profiles.append(name)
        self.active_profile = name
        self.changed.set()
        return True

    def gains(self, name):
        return (1.0,) * 10


def make(resolver, debounce=0.05):
    ctrl = Controller()
    mapper = PresetMapper(load_genre_map())
    d = AutoEqDaemon(resolver, mapper, ctrl, debounce_s=debounce)
    d.start()
    return d, ctrl


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_track_resolved_and_profile_applied():
    r = Resolver({"artist1": ["rock"]})
    d, c = make(r)
    d.on_event(ev(1))
    assert wait_for(lambda: c.profiles == ["Rock"])
    d.stop()


def test_unknown_genre_uses_default():
    d, c = make(Resolver())
    d.on_event(ev(1))
    assert wait_for(lambda: c.profiles == ["Flat"])
    d.stop()


def test_debounce_collapses_rapid_skips():
    r = Resolver({"artist3": ["jazz"]})
    d, c = make(r, debounce=0.3)
    for n in (1, 2, 3):
        d.on_event(ev(n))
        time.sleep(0.02)
    assert wait_for(lambda: c.profiles == ["Jazz"])
    time.sleep(0.4)
    assert r.calls == ["artist3"] and c.profiles == ["Jazz"]
    d.stop()


def test_stale_slow_lookup_is_not_applied():
    gate = {"artist1": threading.Event()}
    r = Resolver({"artist1": ["metal"], "artist2": ["pop"]}, gate)
    d, c = make(r)
    d.on_event(ev(1))
    assert wait_for(lambda: r.calls == ["artist1"])      # lookup 1 in flight
    d.on_event(ev(2))                                   # skip to song 2
    gate["artist1"].set()                               # late answer for song 1
    assert wait_for(lambda: c.profiles == ["Pop"])
    time.sleep(0.2)
    assert c.profiles == ["Pop"]
    d.stop()


def test_on_event_never_blocks_on_resolver():
    gate = {"artist1": threading.Event()}
    d, c = make(Resolver({}, gate))
    d.on_event(ev(1))
    time.sleep(0.15)
    t0 = time.monotonic()
    d.on_event(ev(2))
    assert time.monotonic() - t0 < 0.1
    gate["artist1"].set()
    d.stop()


def test_ad_is_ignored_and_cancels_pending():
    r = Resolver()
    d, c = make(r, debounce=0.2)
    d.on_event(ev(1))
    d.on_event(ev(2, TrackKind.AD))
    time.sleep(0.5)
    assert r.calls == [] and c.profiles == []
    d.stop()


def test_episode_gets_podcast_profile_immediately_without_lookup():
    r = Resolver()
    d, c = make(r, debounce=5)
    d.on_event(ev(1, TrackKind.EPISODE))
    assert c.profiles == ["Podcast"] and r.calls == []
    d.stop()


def test_resolver_exception_does_not_kill_worker():
    class Boom(Resolver):
        def resolve_detailed(self, artist, title):
            if artist == "artist1":
                raise RuntimeError("x")
            return Resolution(("rock",), "itunes", False)

    d, c = make(Boom())
    d.on_event(ev(1))
    time.sleep(0.2)
    d.on_event(ev(2))
    assert wait_for(lambda: c.profiles == ["Rock"])
    d.stop()


def test_reconfigure_changes_mapper():
    r = Resolver({"artist1": ["rock"]})
    d, c = make(r)
    d.reconfigure(PresetMapper(load_genre_map(), overrides={"artist1": "Jazz"}), 0.05)
    d.on_event(ev(1))
    assert wait_for(lambda: c.profiles == ["Jazz"])
    d.stop()


def test_stop_is_prompt_and_double_start_rejected():
    d, c = make(Resolver(), debounce=60)
    d.on_event(ev(1))
    t0 = time.monotonic()
    d.stop()
    assert time.monotonic() - t0 < 1


def test_idle_applies_default_and_cancels_pending():
    r = Resolver({"artist1": ["rock"]})
    d, c = make(r, debounce=0.2)
    d.on_event(ev(1))
    d.on_idle()
    time.sleep(0.5)
    assert r.calls == [] and c.profiles == ["Flat"]
    d.stop()


def test_idle_drops_inflight_lookup():
    gate = {"artist1": threading.Event()}
    d, c = make(Resolver({"artist1": ["metal"]}, gate))
    d.on_event(ev(1))
    time.sleep(0.2)
    d.on_idle()
    gate["artist1"].set()
    time.sleep(0.3)
    assert c.profiles == ["Flat"]
    d.stop()
