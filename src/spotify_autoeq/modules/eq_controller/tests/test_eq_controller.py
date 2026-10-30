import subprocess

import pytest

from spotify_autoeq.modules.eq_controller import (
    BackendError, EqController, EqProfile, PulseEffectsBackend, build_writes, builtin_profiles)
from spotify_autoeq.modules.eq_controller.profiles import BAND_FREQUENCIES_HZ


class FakeBackend:
    def __init__(self, error=None):
        self.applied, self.error, self.closed = [], error, False

    def apply(self, profile):
        if self.error:
            raise self.error
        self.applied.append(profile.name)

    def close(self):
        self.closed = True


def test_builtin_profiles_are_valid():
    profiles = builtin_profiles()
    assert "Flat" in profiles and "Podcast" in profiles
    for p in profiles.values():
        assert len(p.gains_db) == len(BAND_FREQUENCIES_HZ)
        build_writes(p)  # within range
    assert set(profiles["Flat"].gains_db) == {0.0}


def test_same_profile_sends_no_command():
    b = FakeBackend()
    c = EqController(b, builtin_profiles())
    assert c.set_profile("Rock") is True
    assert c.set_profile("Rock") is False
    assert c.set_profile("Pop") is True
    assert b.applied == ["Rock", "Pop"] and c.active_profile == "Pop"


def test_unknown_profile_falls_back_to_default():
    b = FakeBackend()
    c = EqController(b, builtin_profiles(), default_profile="Flat")
    c.set_profile("Nope")
    assert b.applied == ["Flat"]
    with pytest.raises(ValueError):
        EqController(b, builtin_profiles(), default_profile="Missing")


@pytest.mark.parametrize("error", [BackendError("down"), RuntimeError("bug")])
def test_backend_failure_is_contained_and_retried(error):
    b = FakeBackend(error)
    c = EqController(b, builtin_profiles())
    assert c.set_profile("Rock") is False
    assert c.active_profile is None
    b.error = None
    assert c.set_profile("Rock") is True


def test_close_never_raises():
    class Bad(FakeBackend):
        def close(self):
            raise RuntimeError

    EqController(Bad(), builtin_profiles()).close()


def test_build_writes_headroom_and_both_channels():
    w = build_writes(builtin_profiles()["Rock"])
    gain = [x for x in w if x.key == "input-gain"][0]
    assert gain.value == -4.0
    assert {x.path.rstrip("/").split("/")[-1] for x in w if "channel" in x.schema} == {
        "leftchannel", "rightchannel"}
    g = {(x.path, x.key): x.value for x in w if x.key == "band0-gain"}
    assert set(g.values()) == {4.0}
    assert [x for x in w if x.key == "band9-frequency"][0].value == 16000.0


def test_build_writes_rejects_bad_profiles():
    with pytest.raises(BackendError):
        build_writes(EqProfile("short", (0.0,)))
    with pytest.raises(BackendError):
        build_writes(EqProfile("loud", (20.0,) * 10))


class FakeSettings:
    def __init__(self):
        self.batches = []

    def write(self, batch):
        self.batches.append(list(batch))


def make_backend(running, settings=None, **kw):
    state = {"running": running}

    def runner(argv):
        if argv[0] == "pgrep":
            return subprocess.CompletedProcess(argv, 0 if state["running"] else 1, "", "")
        state.setdefault("calls", []).append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    s = settings or FakeSettings()
    return PulseEffectsBackend(s, runner=runner, sleep=lambda t: None, **kw), s, state


def test_first_apply_retriggers_state_then_not():
    backend, s, _ = make_backend(True)
    profiles = builtin_profiles()
    backend.apply(profiles["Rock"])
    backend.apply(profiles["Pop"])
    state_writes = [(i, x.value) for i, batch in enumerate(s.batches)
                    for x in batch if x.key == "state"]
    assert state_writes == [(0, False), (1, True), (2, True)]


def test_first_apply_clears_global_bypass_once():
    backend, s, _ = make_backend(True)
    backend.apply(builtin_profiles()["Rock"])
    backend.apply(builtin_profiles()["Pop"])
    bypass = [x for batch in s.batches for x in batch if x.key == "bypass"]
    assert len(bypass) == 1 and bypass[0].value is False


def test_service_not_running_without_autostart_raises():
    backend, s, _ = make_backend(False, start_service=False)
    with pytest.raises(BackendError):
        backend.apply(builtin_profiles()["Rock"])
    assert s.batches == []


def test_missing_binary_is_backend_error():
    backend, s, _ = make_backend(False, binary="/nonexistent/pulseeffects")
    with pytest.raises(BackendError):
        backend.apply(builtin_profiles()["Rock"])


def test_shutdown_service_runs_quit_and_rearms():
    backend, s, state = make_backend(True)
    backend.apply(builtin_profiles()["Rock"])
    backend.shutdown_service()
    assert state["calls"] == [["pulseeffects", "--quit"]]
    backend.apply(builtin_profiles()["Rock"])
    assert [x.value for b in s.batches for x in b if x.key == "state"] == [False, True, False, True]


def test_last_error_tracks_failures_and_recovery():
    b = FakeBackend(BackendError("down"))
    c = EqController(b, builtin_profiles())
    assert c.last_error is None
    c.set_profile("Rock")
    assert c.last_error == "down"
    b.error = RuntimeError("bug")
    c.set_profile("Rock")
    assert c.last_error == "RuntimeError: bug"
    b.error = None
    assert c.set_profile("Rock") is True and c.last_error is None


def test_gains_of_known_and_unknown_profiles():
    c = EqController(FakeBackend(), builtin_profiles())
    assert len(c.gains("Rock")) == 10 and c.gains("Nope") == ()
