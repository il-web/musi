"""User preferences — a small JSON key/value store.

Loaded once and kept in memory, so reads are safe inside the render loop.
Writes are atomic: this device has no clean shutdown until the power button
exists, and a truncated prefs file must not brick the home screen.
"""
from __future__ import annotations

import json
import logging
import os

from musi.library import config

DEFAULTS: dict[str, object] = {
    "wallpaper": "none",
}

_cache: dict[str, object] | None = None


def reload() -> None:
    """Drop the memory cache; the next read re-reads the file."""
    global _cache
    _cache = None


def _load() -> dict[str, object]:
    global _cache
    if _cache is not None:
        return _cache

    values = dict(DEFAULTS)
    try:
        raw = json.loads(config.prefs_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            values.update(raw)
        else:
            logging.warning("prefs.json is not an object — ignoring it")
    except FileNotFoundError:
        pass                                    # normal on first run
    except (OSError, ValueError):
        logging.warning("prefs.json unreadable — using defaults", exc_info=True)

    _cache = values
    return _cache


def get(key: str, default: object = None) -> object:
    return _load().get(key, DEFAULTS.get(key, default))


def set(key: str, value: object) -> None:
    """Apply in memory, then persist. A failed write keeps the session value."""
    values = _load()
    values[key] = value

    path = config.prefs_path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logging.warning("could not persist prefs", exc_info=True)
        try:
            tmp.unlink()
        except OSError:
            pass
