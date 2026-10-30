import io
import threading
import time

import pytest

from spotify_autoeq.modules.media_listener import (
    FIELD_SEPARATOR as S, PlayerctlListener, TrackKind, build_command,
    build_format, classify_trackid, parse_metadata_line)


def line(trackid, artist="A", title="T", album="Al", status="Playing"):
    return S.join([trackid, artist, title, album, status]) + "\n"


TRACK = "/com/spotify/track/abc"


def test_format_and_command():
    assert build_format().count(S) == 4
    argv = build_command("playerctl", "spotify")
    assert argv[:3] == ["playerctl", "--player=spotify", "--follow"]
    assert argv[-1] == build_format()


@pytest.mark.parametrize("tid,kind", [
    (TRACK, TrackKind.TRACK),
    ("/com/spotify/episode/x", TrackKind.EPISODE),
    ("/com/spotify/ad/x", TrackKind.AD),
    ("/com/spotify/local/x", TrackKind.LOCAL),
    ("spotify:track:x", TrackKind.TRACK),
    ("spotify:ad:x", TrackKind.AD),
    ("spotify:episode:x", TrackKind.EPISODE),
    ("/other/thing", TrackKind.UNKNOWN),
    ("", None),
    ("/org/mpris/MediaPlayer2/TrackList/NoTrack", None),
])
def test_classify(tid, kind):
    assert classify_trackid(tid) is kind


def test_parse_line_and_edge_cases():
    ev = parse_metadata_line(line(TRACK, "Oasis", "I'm Outta Time"))
    assert (ev.artist, ev.title, ev.kind, ev.status) == (
        "Oasis", "I'm Outta Time", TrackKind.TRACK, "Playing")
    assert ev.display == "Oasis - I'm Outta Time"
    assert parse_metadata_line("\n") is None
    short = parse_metadata_line(TRACK + S + "Only\n")
    assert short.artist == "Only" and short.title == "" and short.status == ""
    assert parse_metadata_line(line("")) is None


def test_identity_ignores_status():
    a = parse_metadata_line(line(TRACK, status="Playing"))
    b = parse_metadata_line(line(TRACK, status="Paused"))
    assert a.identity == b.identity


class FakeProc:
    def __init__(self, lines):
        self.stdout = io.StringIO("".join(lines))
        self.terminated = False
        self.code = 0

    def poll(self):
        return self.code if self.terminated or self.done else None

    done = True

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.code


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_dedupe_pause_play_and_ads():
    events = []
    procs = [FakeProc([
        line(TRACK, status="Playing"),
        line(TRACK, status="Paused"),
        line(TRACK, status="Playing"),
        line("/com/spotify/ad/z", "", "Ad"),
        line("/com/spotify/episode/e", "Show", "Ep"),
    ])]

    def factory(argv):
        if procs:
            return procs.pop(0)
        raise FileNotFoundError

    lis = PlayerctlListener(events.append, process_factory=factory,
                            initial_backoff_s=0.01, max_backoff_s=0.02)
    lis.start()
    assert wait_for(lambda: len(events) >= 3)
    lis.stop()
    assert [e.kind for e in events] == [TrackKind.TRACK, TrackKind.AD, TrackKind.EPISODE]


def test_restart_with_backoff_and_same_track_reemitted_after_restart():
    events = []
    batches = [[line(TRACK)], [line(TRACK)]]
    starts = []

    def factory(argv):
        starts.append(time.monotonic())
        if batches:
            return FakeProc(batches.pop(0))
        raise FileNotFoundError("no playerctl")

    lis = PlayerctlListener(events.append, process_factory=factory,
                            initial_backoff_s=0.05, max_backoff_s=0.2)
    lis.start()
    assert wait_for(lambda: len(events) == 2 and len(starts) >= 4)
    lis.stop()
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert gaps[0] >= 0.045
    assert gaps[-1] >= gaps[0]


def test_sink_exception_does_not_kill_listener():
    events = []

    def sink(ev):
        events.append(ev)
        if len(events) == 1:
            raise RuntimeError("boom")

    lis = PlayerctlListener(sink, process_factory=lambda a: FakeProc(
        [line(TRACK), line("/com/spotify/track/b")]),
        initial_backoff_s=0.05, max_backoff_s=0.05)
    lis.start()
    assert wait_for(lambda: len(events) >= 2)
    lis.stop()


def test_stop_unblocks_waiting_process():
    ready = threading.Event()

    class Blocking(FakeProc):
        done = False

        def __init__(self):
            super().__init__([])
            self.stdout = self

        def __iter__(self):
            ready.set()
            while not self.terminated:
                time.sleep(0.01)
            return iter(())

    lis = PlayerctlListener(lambda e: None, process_factory=lambda a: Blocking())
    lis.start()
    assert ready.wait(2)
    t0 = time.monotonic()
    lis.stop(timeout=2)
    assert time.monotonic() - t0 < 2


def test_invalid_backoff_and_double_start():
    with pytest.raises(ValueError):
        PlayerctlListener(lambda e: None, initial_backoff_s=0)
    lis = PlayerctlListener(lambda e: None, process_factory=lambda a: (_ for _ in ()).throw(FileNotFoundError()),
                            initial_backoff_s=0.05)
    lis.start()
    with pytest.raises(RuntimeError):
        lis.start()
    lis.stop()


def test_idle_sink_on_empty_line_and_on_process_exit():
    idle = []
    events = []
    batches = [[line(TRACK), "\n", "\n"], [line(TRACK)]]

    def factory(argv):
        if batches:
            return FakeProc(batches.pop(0))
        raise FileNotFoundError

    lis = PlayerctlListener(events.append, idle_sink=lambda: idle.append(1),
                            process_factory=factory, initial_backoff_s=0.02, max_backoff_s=0.02)
    lis.start()
    assert wait_for(lambda: len(events) == 2 and len(idle) == 2)
    lis.stop()
    assert len(idle) == 2  # empty line once (second one is not a transition) + exit of run 2


def test_idle_sink_not_called_without_prior_track():
    idle = []
    lis = PlayerctlListener(lambda e: None, idle_sink=lambda: idle.append(1),
                            process_factory=lambda a: FakeProc(["\n"]),
                            initial_backoff_s=0.02, max_backoff_s=0.02)
    lis.start()
    time.sleep(0.2)
    lis.stop()
    assert idle == []
