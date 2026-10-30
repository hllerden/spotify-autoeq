import json
from pathlib import Path

import pytest

from spotify_autoeq.modules.genre_resolver import (
    DeezerProvider, GenreCache, GenreResolver, ItunesProvider, LastFmProvider,
    MusicBrainzProvider, ProviderError, artists_match, clean_genres, is_useful_genre,
    normalize_artist)
from spotify_autoeq.modules.genre_resolver.providers.base import RateLimiter

FIX = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIX / name).read_text(encoding="utf-8")


class Net:
    """Fake fetcher serving recorded bodies by URL substring."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        for part, body in self.routes.items():
            if part in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise ProviderError("no route " + url)


NOLIMIT = dict(limiter=None)


def test_validation():
    assert artists_match("Oasis", "oasis")
    assert artists_match("Beyoncé", "Beyonce")
    assert artists_match("Daft Punk feat. Pharrell", "Daft Punk")
    assert artists_match("Calvin Harris", "Calvin Harris, Rihanna")
    assert not artists_match("Oasis", "Nature Sounds Natural Oasis")
    assert not artists_match("", "x")
    assert normalize_artist("Sezen Aksu ft. X") == "sezen aksu"
    assert not is_useful_genre("Music") and not is_useful_genre("2005")
    assert not is_useful_genre("Turkish") and not is_useful_genre("british")
    assert is_useful_genre("Britpop") and is_useful_genre("Turkish Pop")
    assert clean_genres(["music", "Rock", "rock", "Pop"], 5) == ("Rock", "Pop")
    assert clean_genres(["a1", "b1", "c1"], 2) == ("a1", "b1")


def test_musicbrainz_recorded():
    net = Net({"musicbrainz.org": fixture("musicbrainz_oasis.json")})
    genres = MusicBrainzProvider(net, **NOLIMIT).lookup("Oasis", "Wonderwall")
    assert genres[0] == "britpop" and "alternative rock" in genres
    assert "shoegaze" not in genres  # count 0 dropped
    assert net.calls[0][1]["User-Agent"]
    assert MusicBrainzProvider(net, **NOLIMIT).lookup("Nonexistent Band", "x") is None


def test_itunes_recorded():
    net = Net({"itunes.apple.com": fixture("itunes_oasis.json")})
    genres = ItunesProvider(net, **NOLIMIT).lookup("Oasis", "I'm Outta Time")
    assert "Alternative" in genres
    assert ItunesProvider(net, **NOLIMIT).lookup("Someone Else", "x") is None


def test_deezer_recorded_two_requests():
    net = Net({"/search": fixture("deezer_search_oasis.json"),
               "/album/": fixture("deezer_album_oasis.json")})
    genres = DeezerProvider(net, **NOLIMIT).lookup("Oasis", "Wonderwall")
    assert "Indie Rock" in genres
    assert len(net.calls) == 2


def test_lastfm_payload_and_error():
    body = json.dumps({"toptags": {"tag": [
        {"name": "rock", "count": 100}, {"name": "seen live", "count": 90},
        {"name": "rare", "count": 3}]}})
    p = LastFmProvider(Net({"audioscrobbler": body}), "key", **NOLIMIT)
    assert p.lookup("Oasis", "x") == ["rock", "seen live"]
    err = LastFmProvider(Net({"audioscrobbler": json.dumps({"error": 10, "message": "bad key"})}),
                         "key", **NOLIMIT)
    with pytest.raises(ProviderError):
        err.lookup("Oasis", "x")
    with pytest.raises(ValueError):
        LastFmProvider(Net({}), "")


def test_invalid_json_is_provider_error():
    with pytest.raises(ProviderError):
        ItunesProvider(Net({"itunes": "<html>"}), **NOLIMIT).lookup("a", "b")


def test_timeout_passed_to_fetcher():
    net = Net({"itunes": json.dumps({"results": []})})
    ItunesProvider(net, timeout_s=2.5, **NOLIMIT).lookup("a", "b")
    assert net.calls[0][2] == 2.5


def test_rate_limiter_spaces_calls():
    now = [0.0]
    slept = []

    def sleep(d):
        slept.append(d)
        now[0] += d

    rl = RateLimiter(1.0, clock=lambda: now[0], sleep=sleep)
    rl.wait()
    rl.wait()
    rl.wait()
    assert slept == [pytest.approx(1.0), pytest.approx(1.0)]


class Fake:
    def __init__(self, name, result=None, error=None):
        self.name, self.result, self.error, self.calls = name, result, error, 0

    def lookup(self, artist, title):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def make(*providers, now=None):
    clock = (lambda: now[0]) if now else None
    cache = GenreCache(":memory:", positive_ttl_days=30, negative_ttl_days=1,
                       **({"clock": clock} if clock else {}))
    return GenreResolver(providers, cache), cache


def test_chain_first_useful_wins_and_caches():
    a, b = Fake("a", ["music"]), Fake("b", ["Rock"])
    r, _ = make(a, b)
    assert r.resolve("Oasis", "x") == ("Rock",)
    assert r.resolve("OASIS", "y") == ("Rock",)
    assert (a.calls, b.calls) == (1, 1)


def test_negative_cache_ttl():
    now = [1000.0]
    a = Fake("a", None)
    r, _ = make(a, now=now)
    assert r.resolve("X", "t") == ()
    assert r.resolve("X", "t") == ()
    assert a.calls == 1
    now[0] += 86400 + 1
    r.resolve("X", "t")
    assert a.calls == 2


def test_positive_ttl_longer_than_negative():
    now = [0.0]
    a = Fake("a", ["Rock"])
    r, _ = make(a, now=now)
    r.resolve("X", "t")
    now[0] += 29 * 86400
    r.resolve("X", "t")
    assert a.calls == 1
    now[0] += 2 * 86400
    r.resolve("X", "t")
    assert a.calls == 2


def test_provider_failure_falls_through_and_is_not_cached_negative():
    bad = Fake("bad", error=ProviderError("down"))
    r, cache = make(bad)
    assert r.resolve("X", "t") == ()
    assert cache.get("x") is None
    boom = Fake("boom", error=RuntimeError("bug"))
    good = Fake("good", ["Jazz"])
    r2, _ = make(boom, good)
    assert r2.resolve("Y", "t") == ("Jazz",)


def test_empty_artist_and_sqlite_file_persistence(tmp_path):
    r, _ = make(Fake("a", ["Rock"]))
    assert r.resolve("", "t") == ()
    path = tmp_path / "sub" / "g.sqlite3"
    c1 = GenreCache(path)
    c1.put("x", ("Rock", "Pop"))
    c1.close()
    assert GenreCache(path).get("x").genres == ("Rock", "Pop")
    with pytest.raises(ValueError):
        GenreCache(":memory:", positive_ttl_days=0)


def test_purge_expired():
    now = [0.0]
    cache = GenreCache(":memory:", clock=lambda: now[0])
    cache.put("neg", ())
    cache.put("pos", ("Rock",))
    now[0] += 2 * 86400
    assert cache.purge_expired() == 1
    assert cache.get("pos") is not None
