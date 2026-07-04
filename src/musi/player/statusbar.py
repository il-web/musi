"""Shared status bar — rendered at y=0 on every screen.

Content (left → right):
    [musi]        [HH:MM]        [WiFi]  [headphone/BT icon]  [MPD dot]
"""
from __future__ import annotations

import math
from datetime import datetime

import pygame

from musi.player import icons, net_status, theme

BAR_H: int = 26   # height in virtual (320×480) pixels

# ── module-level surface cache (shared across all screens) ────────────────────
_logo_surf:   pygame.Surface | None = None
_time_surf:   pygame.Surface | None = None
_prev_minute: int = -1


# ── public ────────────────────────────────────────────────────────────────────

def draw(surface: pygame.Surface, status, audio_type: str, show_back: bool = False) -> None:
    """Draw the status bar.  Call before drawing any other screen content.

    When show_back is True, a '‹' back chevron is drawn at the far left and the
    "musi" logo shifts right to make room for it.
    """
    global _logo_surf, _time_surf, _prev_minute

    # subtle separator line
    pygame.draw.line(surface, (30, 30, 44), (0, BAR_H), (320, BAR_H), 1)

    cy = BAR_H // 2

    # ── back chevron (left) — only when there's a screen to go back to ─────────
    logo_x = 10
    if show_back:
        icons.draw_chevron_left(surface, 12, cy, theme.WHITE)
        logo_x = 28

    # ── "musi" logo (left) ────────────────────────────────────────────────────
    if _logo_surf is None:
        _logo_surf = theme.render("musi", 13, theme.WHITE, bold=True)
    surface.blit(_logo_surf, (logo_x, cy - _logo_surf.get_height() // 2))

    # ── clock (centre) ────────────────────────────────────────────────────────
    now    = datetime.now()
    minute = now.hour * 60 + now.minute
    if minute != _prev_minute:
        _prev_minute = minute
        _time_surf   = theme.render(now.strftime("%H:%M"), 11, theme.DIM)
    if _time_surf:
        surface.blit(_time_surf, _time_surf.get_rect(centerx=160, centery=cy))

    # ── WiFi icon ─────────────────────────────────────────────────────────────
    wifi_on, strength = net_status.wifi_status()
    _draw_wifi(surface, 252, cy, wifi_on, strength)

    # ── audio icon ────────────────────────────────────────────────────────────
    if audio_type == "bluetooth":
        icons.draw_bt_glyph(surface, 278, cy, theme.ACCENT)
    else:
        # wired or unknown → headphone glyph
        _draw_headphones(surface, 278, cy, theme.DIM)

    # ── MPD connection dot ────────────────────────────────────────────────────
    dot = (80, 200, 80) if status.connected else (200, 80, 80)
    pygame.draw.circle(surface, dot, (308, cy), 3)


# ── icon helpers ──────────────────────────────────────────────────────────────


def _draw_wifi(surface: pygame.Surface, cx: int, cy: int,
               connected: bool, strength: int) -> None:
    """WiFi arcs (~16×12 px); lit arcs show strength, red slash when down."""
    base = cy + 4
    for i, r in enumerate((2, 5, 8)):          # dot, inner arc, outer arc
        lit = connected and strength >= i + 1
        col = theme.DIM if lit else (45, 45, 60)
        if r == 2:
            pygame.draw.circle(surface, col, (cx, base), 2)
        else:
            pts = [(cx + int(r * math.cos(math.pi * (0.5 + 0.45 * t / 10))),
                    base - int(r * math.sin(math.pi * (0.5 + 0.45 * t / 10))))
                   for t in range(-10, 11)]
            pygame.draw.lines(surface, col, False, pts, 2)
    if not connected:
        pygame.draw.line(surface, (200, 90, 90),
                         (cx - 6, base + 2), (cx + 6, base - 8), 2)


def _draw_headphones(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    """Simple headphone silhouette drawn with line segments (~16×13 px)."""
    # Dome (headband) — 9 segments from left to right through the top
    r, base_y = 7, cy - 2
    pts = [
        (cx + int(r * math.cos(math.pi - math.pi * i / 8)),
         base_y - int(r * math.sin(math.pi * i / 8)))
        for i in range(9)
    ]
    pygame.draw.lines(surface, col, False, pts, 2)
    # left ear cup  (aligns with left end of dome at base_y)
    pygame.draw.rect(surface, col, (cx - 9, base_y, 4, 6), border_radius=1)
    # right ear cup
    pygame.draw.rect(surface, col, (cx + 5, base_y, 4, 6), border_radius=1)
