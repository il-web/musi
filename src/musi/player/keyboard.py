"""Reusable on-screen keyboard widget.

Draws a QWERTY keyboard docked at the bottom of the screen and maps taps to key
values. Used by the Search screen (and reusable for WiFi password entry).

Usage:
    kb = Keyboard(top_y=318)
    kb.draw(surface)
    key = kb.key_at(x, y)        # called on a tap inside the keyboard area
    # key is one char, or "BACKSPACE" / "SPACE" / "ENTER" / "TOGGLE" / None

The owner applies the returned key to its text buffer; TOGGLE is handled
internally (swaps letter/number layers).
"""
from __future__ import annotations

import pygame

from musi.player import theme

KEY_W, KEY_H, GAP = 30, 32, 2
ROW_STRIDE = KEY_H + GAP

_LETTERS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
_NUMBERS = ["1234567890", "-/:;()$&@\"", ".,?!'+"]


class Keyboard:
    def __init__(self, top_y: int = 318) -> None:
        self.top   = top_y
        self.layer = 0   # 0 = letters, 1 = numbers/symbols

    @property
    def height(self) -> int:
        return 4 * ROW_STRIDE

    # ── key geometry (shared by draw + hit-test) ────────────────────────────────

    def _keys(self) -> list[tuple[pygame.Rect, str, str]]:
        """Return [(rect, label, value), ...] for the current layer."""
        rows = _NUMBERS if self.layer else _LETTERS
        keys: list[tuple[pygame.Rect, str, str]] = []

        for ri, row in enumerate(rows):
            chars = list(row)
            n = len(chars) + (1 if ri == 2 else 0)   # backspace shares row 2
            total = n * KEY_W + (n - 1) * GAP
            x = (320 - total) // 2
            y = self.top + ri * ROW_STRIDE
            for ch in chars:
                keys.append((pygame.Rect(x, y, KEY_W, KEY_H), ch, ch))
                x += KEY_W + GAP
            if ri == 2:
                keys.append((pygame.Rect(x, y, KEY_W, KEY_H), "", "BACKSPACE"))

        # bottom row: [123/ABC]  [ space ]  [OK]
        y = self.top + 3 * ROW_STRIDE
        keys.append((pygame.Rect(4, y, 46, KEY_H),
                     "ABC" if self.layer else "123", "TOGGLE"))
        keys.append((pygame.Rect(270, y, 46, KEY_H), "", "ENTER"))
        keys.append((pygame.Rect(56, y, 210, KEY_H), "space", "SPACE"))
        return keys

    # ── interaction ─────────────────────────────────────────────────────────────

    def key_at(self, x: int, y: int) -> str | None:
        for rect, _label, value in self._keys():
            if rect.collidepoint(x, y):
                if value == "TOGGLE":
                    self.layer ^= 1
                    return None
                return value
        return None

    # ── drawing ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        for rect, label, value in self._keys():
            wide = value in ("SPACE", "TOGGLE", "ENTER")
            bg = (40, 40, 56) if not wide else theme.CARD_BG
            if value == "ENTER":
                bg = theme.ACCENT
            pygame.draw.rect(surface, bg, rect, border_radius=5)

            if value == "BACKSPACE":
                _draw_backspace(surface, rect.center, theme.WHITE)
            elif value == "ENTER":
                _draw_check(surface, rect.center, theme.WHITE)
            else:
                s = theme.render(label, 15 if not wide else 12, theme.WHITE,
                                 bold=wide)
                surface.blit(s, s.get_rect(center=rect.center))


# ── glyph helpers ───────────────────────────────────────────────────────────────

def _draw_backspace(surface, center, col) -> None:
    cx, cy = center
    pts = [(cx - 8, cy), (cx - 3, cy - 6), (cx + 8, cy - 6),
           (cx + 8, cy + 6), (cx - 3, cy + 6)]
    pygame.draw.polygon(surface, col, pts, 1)
    pygame.draw.line(surface, col, (cx + 1, cy - 3), (cx + 6, cy + 3), 1)
    pygame.draw.line(surface, col, (cx + 6, cy - 3), (cx + 1, cy + 3), 1)


def _draw_check(surface, center, col) -> None:
    cx, cy = center
    pygame.draw.lines(surface, col, False,
                      [(cx - 7, cy), (cx - 2, cy + 6), (cx + 8, cy - 6)], 2)
