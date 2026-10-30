import pytest
import yaml

from spotify_autoeq.modules.preset_mapper import PresetMapper, load_genre_map


@pytest.fixture(scope="module")
def mapper():
    return PresetMapper(load_genre_map(), overrides={"Sezen Aksu": "Acoustic",
                                                    "Daft Punk - Veridis Quo": "Classical"})


def test_bundled_map_is_valid_and_unambiguous():
    gm = load_genre_map()
    seen = {}
    for profile, words in gm.items():
        for w in words:
            assert seen.setdefault(w.casefold(), profile) == profile, w


@pytest.mark.parametrize("genre,profile", [
    ("anatolian rock", "Rock"),
    ("melodic techno", "Electronic"),
    ("Hip-Hop/Rap", "HipHop"),
    ("Türk Sanat Müziği", "Acoustic"),
    ("synthpop", "Pop"),
    ("Alternatif", "Rock"),
    ("progressive metal", "Metal"),
    ("Klasik", "Classical"),
])
def test_single_genre(mapper, genre, profile):
    assert mapper.match_genre(genre) == profile


def test_unknown_and_empty_give_default(mapper):
    assert mapper.map_genres(["zzz unknown"]) == "Flat"
    assert mapper.map_genres([]) == "Flat"
    assert mapper.match_genre("") is None


def test_voting_prefers_earlier_and_majority(mapper):
    assert mapper.map_genres(["britpop", "alternative rock", "rock", "indie rock"]) == "Rock"
    assert mapper.map_genres(["pop", "rock"]) == "Pop"
    assert mapper.map_genres(["jazz", "pop", "pop", "pop"]) == "Pop"
    assert mapper.map_genres(["pop", "unknownthing", "rock"]) == "Pop"


def test_overrides(mapper):
    assert mapper.profile_for("sezen aksu", "x", ["rock"]) == "Acoustic"
    assert mapper.profile_for("Daft Punk", "Veridis Quo", ["house"]) == "Classical"
    assert mapper.profile_for("Daft Punk", "Other", ["house"]) == "Electronic"


def test_custom_default_and_profiles():
    m = PresetMapper({"Rock": ["rock"]}, default_profile="Neutral", podcast_profile="Voice")
    assert m.map_genres(["x"]) == "Neutral"
    assert m.profiles == {"Rock", "Neutral", "Voice"}


def test_load_genre_map_rejects_bad_file(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump({"Rock": "rock"}))
    with pytest.raises(ValueError):
        load_genre_map(p)
