"""Configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from spotify_autoeq import __version__

KNOWN_PROVIDERS = ("musicbrainz", "lastfm", "itunes", "deezer")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    """Raised when the configuration file is unreadable or invalid."""


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    journal: bool = True


@dataclass(frozen=True)
class ResolverConfig:
    http_timeout_s: float = 4.0
    providers: tuple[str, ...] = ("musicbrainz", "itunes", "deezer")
    cache_path: Path = field(
        default_factory=lambda: Path("~/.cache/spotify-autoeq/genres.sqlite3").expanduser())
    positive_ttl_days: float = 30.0
    negative_ttl_days: float = 1.0
    user_agent: str = f"spotify-autoeq/{__version__}"
    lastfm_api_key: str = ""


@dataclass(frozen=True)
class MapperConfig:
    default_profile: str = "Flat"
    podcast_profile: str = "Podcast"
    overrides: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EqConfig:
    backend: str = "pulseeffects"
    preset_dir: Path = field(
        default_factory=lambda: Path("~/.config/PulseEffects/output").expanduser())


@dataclass(frozen=True)
class StatusConfig:
    enabled: bool = True
    path: Optional[Path] = None
    """``None`` selects ``$XDG_RUNTIME_DIR/spotify-autoeq/status.json``."""


@dataclass(frozen=True)
class Config:
    player: str = "spotify"
    debounce_s: float = 1.5
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    resolver: ResolverConfig = field(default_factory=ResolverConfig)
    mapper: MapperConfig = field(default_factory=MapperConfig)
    eq: EqConfig = field(default_factory=EqConfig)
    status: StatusConfig = field(default_factory=StatusConfig)


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "spotify-autoeq" / "config.yaml"


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"'{key}' must be a mapping")
    return value


def _reject_unknown(section: str, raw: Mapping[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        where = f"'{section}': " if section else ""
        raise ConfigError(f"{where}unknown key(s): {', '.join(map(str, unknown))}")


def _number(name: str, value: Any, *, minimum: float, exclusive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{name}' must be a number")
    ok = value > minimum if exclusive else value >= minimum
    if not ok:
        op = ">" if exclusive else ">="
        raise ConfigError(f"'{name}' must be {op} {minimum}")
    return float(value)


def _text(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"'{name}' must be a string")
    if not allow_empty and not value.strip():
        raise ConfigError(f"'{name}' must not be empty")
    return value


def _path(name: str, value: Any) -> Path:
    return Path(_text(name, value)).expanduser()


def _parse_logging(raw: Mapping[str, Any]) -> LoggingConfig:
    _reject_unknown("logging", raw, ("level", "journal"))
    d = LoggingConfig()
    level = _text("logging.level", raw.get("level", d.level)).upper()
    if level not in LOG_LEVELS:
        raise ConfigError(f"'logging.level' must be one of {', '.join(LOG_LEVELS)}")
    journal = raw.get("journal", d.journal)
    if not isinstance(journal, bool):
        raise ConfigError("'logging.journal' must be a boolean")
    return LoggingConfig(level=level, journal=journal)


def _parse_resolver(raw: Mapping[str, Any]) -> ResolverConfig:
    _reject_unknown(
        "resolver",
        raw,
        ("http_timeout_s", "providers", "cache_path", "positive_ttl_days",
         "negative_ttl_days", "user_agent", "lastfm_api_key"),
    )
    d = ResolverConfig()
    providers = raw.get("providers", list(d.providers))
    if not isinstance(providers, (list, tuple)) or not providers:
        raise ConfigError("'resolver.providers' must be a non-empty list")
    names = tuple(_text("resolver.providers[]", p).lower() for p in providers)
    bad = [p for p in names if p not in KNOWN_PROVIDERS]
    if bad:
        raise ConfigError(
            f"'resolver.providers': unknown provider(s) {', '.join(bad)}; "
            f"known: {', '.join(KNOWN_PROVIDERS)}"
        )
    if len(set(names)) != len(names):
        raise ConfigError("'resolver.providers' must not contain duplicates")
    key = _text("resolver.lastfm_api_key", raw.get("lastfm_api_key", d.lastfm_api_key),
                allow_empty=True)
    if "lastfm" in names and not key.strip():
        raise ConfigError("'resolver.lastfm_api_key' is required when 'lastfm' is enabled")
    return ResolverConfig(
        http_timeout_s=_number("resolver.http_timeout_s",
                               raw.get("http_timeout_s", d.http_timeout_s),
                               minimum=0, exclusive=True),
        providers=names,
        cache_path=_path("resolver.cache_path", raw.get("cache_path", str(d.cache_path))),
        positive_ttl_days=_number("resolver.positive_ttl_days",
                                  raw.get("positive_ttl_days", d.positive_ttl_days),
                                  minimum=0, exclusive=True),
        negative_ttl_days=_number("resolver.negative_ttl_days",
                                  raw.get("negative_ttl_days", d.negative_ttl_days),
                                  minimum=0, exclusive=True),
        user_agent=_text("resolver.user_agent", raw.get("user_agent", d.user_agent)),
        lastfm_api_key=key.strip(),
    )


def _parse_mapper(raw: Mapping[str, Any]) -> MapperConfig:
    _reject_unknown("mapper", raw, ("default_profile", "podcast_profile", "overrides"))
    d = MapperConfig()
    overrides_raw = raw.get("overrides") or {}
    if not isinstance(overrides_raw, Mapping):
        raise ConfigError("'mapper.overrides' must be a mapping")
    overrides = {
        _text("mapper.overrides key", k).strip().casefold(): _text("mapper.overrides value", v)
        for k, v in overrides_raw.items()
    }
    return MapperConfig(
        default_profile=_text("mapper.default_profile",
                              raw.get("default_profile", d.default_profile)),
        podcast_profile=_text("mapper.podcast_profile",
                              raw.get("podcast_profile", d.podcast_profile)),
        overrides=overrides,
    )


def _parse_eq(raw: Mapping[str, Any]) -> EqConfig:
    _reject_unknown("eq", raw, ("backend", "preset_dir"))
    d = EqConfig()
    backend = _text("eq.backend", raw.get("backend", d.backend)).lower()
    if backend != "pulseeffects":
        raise ConfigError("'eq.backend' must be 'pulseeffects'")
    return EqConfig(backend=backend,
                    preset_dir=_path("eq.preset_dir", raw.get("preset_dir", str(d.preset_dir))))


def _parse_status(raw: Mapping[str, Any]) -> StatusConfig:
    _reject_unknown("status", raw, ("enabled", "path"))
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("'status.enabled' must be a boolean")
    path = raw.get("path")
    return StatusConfig(enabled=enabled, path=None if path is None else _path("status.path", path))


def parse_config(raw: Optional[Mapping[str, Any]]) -> Config:
    """Validate a decoded YAML mapping and return an immutable :class:`Config`."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigError("top level of the configuration must be a mapping")
    _reject_unknown("", raw, ("player", "debounce_s", "logging", "resolver", "mapper", "eq", "status"))
    d = Config()
    return Config(
        player=_text("player", raw.get("player", d.player)),
        debounce_s=_number("debounce_s", raw.get("debounce_s", d.debounce_s), minimum=0),
        logging=_parse_logging(_section(raw, "logging")),
        resolver=_parse_resolver(_section(raw, "resolver")),
        mapper=_parse_mapper(_section(raw, "mapper")),
        eq=_parse_eq(_section(raw, "eq")),
        status=_parse_status(_section(raw, "status")),
    )


def load_config(path: Optional[Path] = None) -> Config:
    """Load the configuration from ``path`` (default: XDG config location).

    A missing file at the default location yields the defaults; a missing file
    that was requested explicitly is an error.
    """
    explicit = path is not None
    target = Path(path).expanduser() if explicit else default_config_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"configuration file not found: {target}") from None
        return Config()
    except OSError as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {target}: {exc}") from exc
    try:
        return parse_config(raw)
    except ConfigError as exc:
        raise ConfigError(f"{target}: {exc}") from None
