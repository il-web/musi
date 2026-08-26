"""Launcher app tiles — rounded gradient squares with code-drawn glyphs.

No image assets: the panel is 320×480 and a handful of gradients cost less
than shipping and scaling PNGs. Each tile is built once and cached for the
life of the process.
"""
from __future__ import annotations

import math

import pygame

TILE: int = 118

KEYS: tuple[str, ...] = ("music", "settings", "clock", "sleep", "customization")

# (top-left colour, bottom-right colour) — the first is also the page accent
_GRADIENTS: dict[str, tuple[tuple, tuple]] = {
    "music":         ((255,  92, 138), (122,  59, 255)),
    "settings":      ((110, 140, 255), ( 43,  43, 110)),
    "clock":         (( 46, 196, 182), ( 11, 110, 110)),
    "sleep":         ((155,  92, 255), ( 59,  31, 110)),
    "customization": ((255, 170,  60), (200,  60,  20)),
}

_cache: dict[tuple[str, int], pygame.Surface] = {}


def accent(key: str) -> tuple:
    """The tile's leading colour — used for dots and page highlights."""
    return _GRADIENTS[key][0]


def render_tile(key: str, size: int = TILE) -> pygame.Surface:
    """Rounded gradient tile with the app's glyph. Cached per (key, size)."""
    if key not in _GRADIENTS:
        raise KeyError(key)
    hit = _cache.get((key, size))
    if hit is not None:
        return hit

    c0, c1 = _GRADIENTS[key]

    # Diagonal gradient: the four corners of a 2x2 surface bilinearly upscaled.
    # Interpolating in one step avoids the seam a per-row segment loop leaves
    # down the middle, and costs one scale instead of `size` draw calls.
    mid = tuple((a + b) // 2 for a, b in zip(c0, c1))
    grad = pygame.Surface((2, 2))
    grad.set_at((0, 0), c0)
    grad.set_at((1, 0), mid)
    grad.set_at((0, 1), mid)
    grad.set_at((1, 1), c1)
    tile = pygame.transform.smoothscale(grad, (size, size)).convert_alpha()

    # rounded-corner mask
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, size, size),
                     border_radius=int(size * 0.22))
    tile.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    _GLYPHS[key](tile, size)
    _cache[(key, size)] = tile
    return tile


# ── glyphs (drawn white, centred, scaled to the tile) ─────────────────────────

def _glyph_music(s: pygame.Surface, n: int) -> None:
    w = (255, 255, 255)
    cx, cy = n // 2, n // 2
    u = n / 118.0
    stem_x, top_y, bot_y = cx + int(6 * u), cy - int(26 * u), cy + int(18 * u)
    pygame.draw.line(s, w, (stem_x, top_y), (stem_x, bot_y), max(2, int(4 * u)))
    pygame.draw.line(s, w, (cx - int(18 * u), top_y + int(6 * u)),
                     (cx - int(18 * u), bot_y + int(6 * u)), max(2, int(4 * u)))
    pygame.draw.line(s, w, (cx - int(18 * u), top_y + int(6 * u)),
                     (stem_x, top_y), max(2, int(4 * u)))
    pygame.draw.circle(s, w, (cx - int(24 * u), bot_y + int(6 * u)), int(8 * u))
    pygame.draw.circle(s, w, (stem_x - int(6 * u), bot_y), int(8 * u))


def _glyph_settings(s: pygame.Surface, n: int) -> None:
    w = (255, 255, 255)
    cx, cy = n // 2, n // 2
    u = n / 118.0
    for i in range(8):                             # gear teeth
        a = math.pi * i / 4
        x1, y1 = cx + int(26 * u * math.cos(a)), cy + int(26 * u * math.sin(a))
        x2, y2 = cx + int(34 * u * math.cos(a)), cy + int(34 * u * math.sin(a))
        pygame.draw.line(s, w, (x1, y1), (x2, y2), max(3, int(7 * u)))
    pygame.draw.circle(s, w, (cx, cy), int(24 * u), max(2, int(6 * u)))
    pygame.draw.circle(s, w, (cx, cy), int(8 * u))


def _glyph_clock(s: pygame.Surface, n: int) -> None:
    w = (255, 255, 255)
    cx, cy = n // 2, n // 2
    u = n / 118.0
    pygame.draw.circle(s, w, (cx, cy), int(32 * u), max(2, int(4 * u)))
    pygame.draw.line(s, w, (cx, cy), (cx, cy - int(20 * u)), max(2, int(4 * u)))
    pygame.draw.line(s, w, (cx, cy), (cx + int(14 * u), cy + int(8 * u)),
                     max(2, int(4 * u)))


def _glyph_sleep(s: pygame.Surface, n: int) -> None:
    """Crescent — a filled disc with an offset disc punched out."""
    w = (255, 255, 255)
    cx, cy = n // 2, n // 2
    u = n / 118.0
    moon = pygame.Surface((n, n), pygame.SRCALPHA)
    pygame.draw.circle(moon, w, (cx, cy), int(30 * u))
    pygame.draw.circle(moon, (0, 0, 0, 0), (cx + int(12 * u), cy - int(10 * u)),
                       int(26 * u))
    s.blit(moon, (0, 0))


def _glyph_customization(s: pygame.Surface, n: int) -> None:
    """Picture frame with a sun and a mountain."""
    w = (255, 255, 255)
    cx, cy = n // 2, n // 2
    u = n / 118.0
    frame = pygame.Rect(0, 0, int(60 * u), int(48 * u))
    frame.center = (cx, cy)
    pygame.draw.rect(s, w, frame, max(2, int(4 * u)),
                     border_radius=int(6 * u))
    pygame.draw.circle(s, w, (frame.x + int(16 * u), frame.y + int(14 * u)),
                       int(5 * u))
    pygame.draw.polygon(s, w, [
        (frame.x + int(6 * u),  frame.bottom - int(6 * u)),
        (frame.x + int(26 * u), frame.y + int(22 * u)),
        (frame.x + int(46 * u), frame.bottom - int(6 * u)),
    ])


_GLYPHS = {
    "music":         _glyph_music,
    "settings":      _glyph_settings,
    "clock":         _glyph_clock,
    "sleep":         _glyph_sleep,
    "customization": _glyph_customization,
}
