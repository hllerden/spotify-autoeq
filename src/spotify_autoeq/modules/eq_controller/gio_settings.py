"""Gio/GSettings implementation of the settings writer (needs python3-gi)."""

from __future__ import annotations

from typing import Any, Sequence

from .ports import BackendError, SettingWrite


class GioSettingsWriter:
    def __init__(self) -> None:
        try:
            import gi  # type: ignore[import-not-found]
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib  # type: ignore[import-not-found]
        except (ImportError, ValueError) as exc:
            raise BackendError(f"python3-gi is not available: {exc}") from exc
        self._gio, self._glib = Gio, GLib
        self._cache: dict[tuple[str, str], Any] = {}

    def _settings(self, schema: str, path: str) -> Any:
        key = (schema, path)
        if key not in self._cache:
            source = self._gio.SettingsSchemaSource.get_default()
            if source is None or source.lookup(schema, True) is None:
                raise BackendError(f"GSettings schema not installed: {schema}")
            self._cache[key] = self._gio.Settings.new_with_path(schema, path)
        return self._cache[key]

    def write(self, batch: Sequence[SettingWrite]) -> None:
        touched = []
        try:
            for item in batch:
                settings = self._settings(item.schema, item.path)
                if settings not in touched:
                    settings.delay()
                    touched.append(settings)
                type_string = settings.get_value(item.key).get_type_string()
                settings.set_value(item.key, self._glib.Variant(type_string, item.value))
            for settings in touched:
                settings.apply()
            self._gio.Settings.sync()
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 - GLib errors are not a stable hierarchy
            for settings in touched:
                settings.revert()
            raise BackendError(f"GSettings write failed: {exc}") from exc
