"""Home-screen wallpapers — loaded once, cropped to the launcher page area.

The launcher page area is 320x410 but the artwork is authored at 320x480, so
each image is scaled to width and centre-cropped vertically. Scaling to fit
instead would squash the circular blobs into ovals.

Everything here is cached, including failures: surface() is called from the
render loop and must never reach the disk twice.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pygame

NAMES: tuple[str, ...] = ("none", "warm", "cool")

WIDTH  = 320
HEIGHT = 410          # launcher PAGE_BOTTOM - PAGE_Y

# 0.0 keeps the top of the image, 1.0 keeps the bottom, 0.5 centres the crop.
CROP_BIAS = 0.5

_DIR = Path(__file__).parent / "assets" / "wallpapers"

_surfaces:  dict[str, pygame.Surface | None] = {}
_thumbs:    dict[tuple[str, tuple[int, int]], pygame.Surface | None] = {}


def clear_cache() -> None:
    _surfaces.clear()
    _thumbs.clear()


def surface(name: str) -> pygame.Surface | None:
    """The wallpaper for ``name``, or None for "none" / any failure."""
    if name not in _surfaces:
        _surfaces[name] = _load(name)
    return _surfaces[name]


def thumbnail(name: str, size: tuple[int, int]) -> pygame.Surface | None:
    """A scaled copy for the picker. Cached per (name, size)."""
    key = (name, size)
    if key not in _thumbs:
        full = surface(name)
        _thumbs[key] = (pygame.transform.smoothscale(full, size)
                        if full is not None else None)
    return _thumbs[key]


def _load(name: str) -> pygame.Surface | None:
    if name == "none" or name not in NAMES:
        return None
    try:
        img = pygame.image.load(str(_DIR / f"{name}.jpg"))
    except (pygame.error, OSError):
        logging.warning("wallpaper %r failed to load", name, exc_info=True)
        return None
    return _fit(img).convert()


def _fit(img: pygame.Surface) -> pygame.Surface:
    """Scale to WIDTH, then crop vertically to HEIGHT, keeping aspect."""
    iw, ih = img.get_size()
    if (iw, ih) == (WIDTH, HEIGHT):
        return img

    scaled_h = max(HEIGHT, round(ih * WIDTH / iw))
    img = pygame.transform.smoothscale(img, (WIDTH, scaled_h))
    if scaled_h == HEIGHT:
        return img

    top = int((scaled_h - HEIGHT) * CROP_BIAS)
    out = pygame.Surface((WIDTH, HEIGHT))
    out.blit(img, (0, -top))
    return out
