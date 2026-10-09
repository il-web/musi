"""Visual theme — colours and font helpers."""

from __future__ import annotations

import re
from functools import lru_cache

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
    """Render text, truncating with '...' only if wider than max_width.

    Text that fits is left alone — the ellipsis budget is applied *after*
    deciding the string overflows, not before, or anything landing within one
    ellipsis-width of the limit would be clipped for no reason.
    """
    f = font(size, bold)
    if max_width > 0 and text and f.size(text)[0] > max_width:
        while text and f.size(text + "...")[0] > max_width:
            text = text[:-1]
        text = text + "..." if text else text
    return f.render(visual(text), True, colour)


# Hebrew / Arabic ranges. pygame draws characters strictly left to right in
# the order they are stored, so right-to-left text came out mirrored. The
# Unicode bidi algorithm reorders it into display order — including mixed
# lines like "Radios 100FM (רדיוס 100FM)". Truncation above works on the
# logical text first, so "..." lands at the end of what a reader reads.
_RTL = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")

try:
    from bidi import get_display as _get_display
except ImportError:                      # older python-bidi, or not installed
    try:
        from bidi.algorithm import get_display as _get_display
    except ImportError:
        _get_display = None


def visual(text: str) -> str:
    """``text`` in display order (a no-op for left-to-right text)."""
    if not text or _get_display is None or not _RTL.search(text):
        return text
    try:
        return _get_display(text)
    except Exception:
        return text


@lru_cache(maxsize=256)
def render_cached(
    text: str,
    size: int,
    colour: tuple = TEXT,
    bold: bool = False,
    max_width: int = 0,
) -> pygame.Surface:
    """render() memoised for text drawn every frame — list and grid labels.

    Screens that redraw the same labels each frame (the Home shelves, the
    Library grid) would otherwise pay a fresh rasterisation plus, with
    max_width set, one f.size() call per character trimmed. The returned
    surface is shared: callers must treat it as read-only.
    """
    return render(text, size, colour, bold, max_width)


def wrap(text: str, size: int, bold: bool, max_w: int) -> list[str]:
    """Word-wrap into as many rows as it takes. Nothing is ever truncated.

    A single word wider than max_w is left long — theme.render will clip it,
    which beats dropping it.
    """
    f = font(size, bold)
    if not text or f.size(text)[0] <= max_w:
        return [text]
    rows: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and f.size(trial)[0] > max_w:
            rows.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        rows.append(cur)
    return rows or [text]
