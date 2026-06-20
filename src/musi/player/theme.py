"""Visual theme — colours and font helpers."""

from __future__ import annotations

import pygame

# ── palette ───────────────────────────────────────────────────────────────────
BG       = (10,  10,  15)   # near-black background
CARD_BG  = (22,  22,  32)   # card / panel background
TEXT     = (240, 240, 240)  # primary text
DIM      = (120, 120, 135)  # secondary / dimmed text
ACCENT   = (255,  92, 138)  # default accent (hot pink — overridden by album palette)
WHITE    = (255, 255, 255)
BLACK    = (0,   0,   0)


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    """Convert '#rrggbb' to (r, g, b)."""
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def brighten(colour: tuple, factor: float = 1.4) -> tuple[int, int, int]:
    return tuple(min(255, int(c * factor)) for c in colour)


def darken(colour: tuple, factor: float = 0.6) -> tuple[int, int, int]:
    return tuple(int(c * factor) for c in colour)


# ── fonts ─────────────────────────────────────────────────────────────────────
# Preference list — first match wins; None = pygame built-in fallback
_FONT_NAMES = ["segoeui", "dejavusans", "freesans", "liberationsans", "ubuntu", "arial"]
_cache: dict[tuple, pygame.font.Font] = {}


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    if key not in _cache:
        for name in _FONT_NAMES:
            f = pygame.font.SysFont(name, size, bold=bold)
            # SysFont returns a font even on mismatch, but the name will differ
            # if the font wasn't found pygame falls back to default — accept that
            if f is not None:
                _cache[key] = f
                break
        else:
            _cache[key] = pygame.font.Font(None, size)   # pygame built-in
    return _cache[key]


def render(
    text: str,
    size: int,
    colour: tuple = TEXT,
    bold: bool = False,
    max_width: int = 0,
) -> pygame.Surface:
    """Render text, truncating with '…' if wider than max_width."""
    f = font(size, bold)
    if max_width > 0:
        while text and f.size(text)[0] > max_width:
            text = text[:-1]
        if text and f.size(text + "...")[0] > max_width and len(text) > 3:
            text = text[:-3] + "..."
    return f.render(text, True, colour)
