"""Process-wide settings kept in module-level state."""

from __future__ import annotations

DEFAULTS = {"currency": "USD", "locale": "en_US"}
_overrides: dict[str, str] = {}


def configure(**values: str) -> None:
    _overrides.update(values)


def get(name: str) -> str:
    return _overrides.get(name, DEFAULTS[name])
