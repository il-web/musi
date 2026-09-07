"""Blurred now-playing background.

The blur is a downscale to 16x24 and a smoothscale back up — a real gaussian
is far too slow on a Pi 3, and at this scrim strength the difference is not
visible. Cached by art path: the render loop must never pay the decode.

surface() returns None when there is nothing to blur, so callers fall back to
theme.BG. That makes "nothing playing", "art missing" and "load failed" all
take the same path instead of each being a special case.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pygame

from musi.player import art_cache, theme

WIDTH  = 320
HEIGHT = 480

_BLUR  = (16, 24)              # downscale target — the blur radius, in effect
_SCRIM = (6, 6, 12, 170)       # dimming laid over the blur

# Per-track guard. art_cache.get_track_art_and_palette runs SQL and is NOT
# cached, so an unguarded call from draw() is a query every frame — exactly the
# regression tests/test_draw_loop_cost.py exists to prevent.
_track_path:   str = "UNSET"
_track_bg:     "pygame.Surface | None" = None
_track_accent: tuple = ()


def clear_cache() -> None:
    global _track_path, _track_bg, _track_accent
    surface.cache_clear()
    _track_path, _track_bg, _track_accent = "UNSET", None, theme.ACCENT


@lru_cache(maxsize=4)
def surface(art_path: str) -> "pygame.Surface | None":
    """A 320x480 blurred, dimmed backdrop for ``art_path``, or None."""
    if not art_path or not Path(art_path).exists():
        return None
    try:
        img = pygame.image.load(art_path).convert()
    except (pygame.error, OSError):
        logging.warning("backdrop %r failed to load", art_path, exc_info=True)
        return None

    small = pygame.transform.smoothscale(img, _BLUR)
    out   = pygame.transform.smoothscale(small, (WIDTH, HEIGHT))

    scrim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    scrim.fill(_SCRIM)
    out.blit(scrim, (0, 0))
    return out


def for_track(db, status) -> tuple["pygame.Surface | None", tuple]:
    """(backdrop, accent) for the playing track — one query per track change.

    Screens call this every frame. The guard means the SQL join and the two
    smoothscales happen only when status.path actually changes.
    """
    global _track_path, _track_bg, _track_accent
    path = getattr(status, "path", "") or ""

    if path == _track_path:
        return _track_bg, (_track_accent or theme.ACCENT)

    _track_path   = path
    _track_bg     = None
    _track_accent = theme.ACCENT

    if not path or db is None:
        return None, theme.ACCENT

    res = art_cache.get_track_art_and_palette(
        db, path, getattr(status, "artist", ""), getattr(status, "album", ""))
    _track_bg     = surface(res.get("backdrop_path") or "")
    _track_accent = art_cache.parse_palette(res.get("palette"), do_brighten=True)
    return _track_bg, _track_accent
