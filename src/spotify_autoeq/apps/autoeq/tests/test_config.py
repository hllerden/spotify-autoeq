import io
import logging
from pathlib import Path

import pytest

from spotify_autoeq.apps.autoeq.config import (
    Config, ConfigError, default_config_path, load_config, parse_config)
from spotify_autoeq.apps.autoeq.log import ROOT_LOGGER, configure_logging

EXAMPLE = Path(__file__).resolve().parents[1] / "data" / "config.example.yaml"


def write(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_empty_mapping_yields_defaults():
    assert parse_config({}) == Config()
    assert parse_config(None) == Config()


def test_example_file_is_valid():
    cfg = load_config(EXAMPLE)
    assert cfg.player == "spotify"
    assert cfg.resolver.providers[0] == "musicbrainz"
    assert not str(cfg.eq.preset_dir).startswith("~")


def test_overrides_and_values_applied(tmp_path):
    cfg = load_config(write(tmp_path, (
        "debounce_s: 0\nlogging: {level: debug, journal: false}\n"
        "resolver: {providers: [itunes], http_timeout_s: 2}\n"
        "mapper: {overrides: {'Daft Punk': Dance}}\n")))
    assert cfg.debounce_s == 0
    assert cfg.logging.level == "DEBUG" and cfg.logging.journal is False
    assert cfg.resolver.providers == ("itunes",)
    assert cfg.mapper.overrides == {"daft punk": "Dance"}


@pytest.mark.parametrize("raw", [
    {"bogus": 1},
    {"debounce_s": -1},
    {"debounce_s": True},
    {"player": ""},
    {"logging": {"level": "LOUD"}},
    {"logging": {"journal": "yes"}},
    {"logging": [1]},
    {"resolver": {"providers": []}},
    {"resolver": {"providers": ["nope"]}},
    {"resolver": {"providers": ["itunes", "itunes"]}},
    {"resolver": {"providers": ["lastfm"]}},
    {"resolver": {"http_timeout_s": 0}},
    {"resolver": {"positive_ttl_days": -3}},
    {"mapper": {"overrides": [1]}},
    {"eq": {"backend": "easyeffects"}},
    {"eq": {"extra": 1}},
])
def test_invalid_config_rejected(raw):
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_top_level_not_mapping(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "- a\n- b\n"))


def test_invalid_yaml_and_missing_explicit_file(tmp_path):
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "a: [unclosed"))
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_error_names_file(tmp_path):
    p = write(tmp_path, "debounce_s: -1\n")
    with pytest.raises(ConfigError, match=str(p)):
        load_config(p)


def test_missing_default_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "spotify-autoeq" / "config.yaml"
    assert load_config() == Config()


def test_logging_single_point_idempotent():
    buf = io.StringIO()
    configure_logging("INFO", True, buf)
    logger = configure_logging("WARNING", True, buf)
    assert len(logger.handlers) == 1 and logger.name == ROOT_LOGGER
    assert logger.propagate is False
    logging.getLogger(f"{ROOT_LOGGER}.x").info("hidden")
    logging.getLogger(f"{ROOT_LOGGER}.x").warning("shown")
    out = buf.getvalue()
    assert "shown" in out and "hidden" not in out
    assert out.startswith("WARNING ")
