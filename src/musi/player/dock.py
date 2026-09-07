"""Merged dock — the music app's bottom chrome.

The now-playing strip sits directly on the nav row, one component rather than
two stacked bars. The strip is minibar drawn at DOCK_Y, so art loading, palette
parsing and text caching have exactly one implementation.

Music-app-only: the launcher, clock, sleep, customization, artwork and album
screens draw a plain minibar and must never show music nav tabs.

TABS drives the layout, so a fourth destination (radio) is one appended entry.
"""
from __future__ import annotations

import pygame

from musi.player import minibar, theme

DOCK_Y = 480 - 74           # 406
DOCK_H = 74
NAV_H  = 30
NAV_Y  = 480 - NAV_H        # 450

TABS: list[tuple[str, str]] = [
    ("home",    "Home"),
    ("library", "Library"),
    ("search",  "Search"),
]

_NAV_BG = (20, 20, 30)
_OFF    = (120, 120, 135)


def tab_width() -> int:
    return 320 // len(TABS)


def draw(surface: pygame.Surface, app, status, active: int, accent: tuple,
         strip: bool = True) -> None:
    """Draw the dock. ``strip`` False keeps the nav but hides now-playing.

    Search passes strip=False: its keyboard docks over the strip's pixels, but
    hiding the nav too would leave no way off the Search tab.
    """
    if strip:
        minibar.draw(surface, app, status, y=DOCK_Y)

    pygame.draw.rect(surface, _NAV_BG, (0, NAV_Y, 320, NAV_H))
    pygame.draw.line(surface, (44, 44, 60), (0, NAV_Y), (320, NAV_Y), 1)

    tw = tab_width()
    for i, (kind, label) in enumerate(TABS):
        cx  = i * tw + tw // 2
        col = accent if i == active else _OFF
        _icon(surface, kind, cx, NAV_Y + 11, col)
        s = theme.render(label, 8, col, bold=(i == active))
        surface.blit(s, s.get_rect(centerx=cx, y=NAV_Y + 20))


def hit(x: int, y: int) -> "tuple[str, int] | None":
    """Classify a dock tap.

    ('tab', i) on the nav row; ('toggle', 0) / ('open', 0) on the strip; None
    above the dock. The int is meaningful only for 'tab'.
    """
    if y < DOCK_Y:
        return None
    if y >= NAV_Y:
        return ("tab", min(len(TABS) - 1, x // tab_width()))
    zone = minibar.hit(x, y, bar_y=DOCK_Y)
    return (zone, 0) if zone else None


# ── nav icons ─────────────────────────────────────────────────────────────────

def _icon(surface: pygame.Surface, kind: str, cx: int, cy: int,
          col: tuple) -> None:
    if kind == "home":
        pygame.draw.polygon(surface, col,
                            [(cx, cy - 7), (cx + 8, cy + 1), (cx - 8, cy + 1)])
        pygame.draw.rect(surface, col, (cx - 6, cy + 1, 12, 7), border_radius=1)
    elif kind == "library":
        for i, h in enumerate((12, 8, 14)):
            pygame.draw.rect(surface, col, (cx - 7 + i * 6, cy + 7 - h, 4, h),
                             border_radius=1)
    elif kind == "search":
        pygame.draw.circle(surface, col, (cx - 1, cy - 1), 6, 2)
        pygame.draw.line(surface, col, (cx + 4, cy + 4), (cx + 8, cy + 8), 2)
