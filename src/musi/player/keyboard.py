"""Reusable on-screen keyboard widget.

Draws a QWERTY keyboard docked at the bottom of the screen and maps touches to
key values. Used by the Search screen, WiFi password entry and text prompts.

Usage:
    kb = Keyboard(top_y=HOST_BOTTOM - HEIGHT)
    kb.draw(surface)

    # touch: capture the gesture so a sliding finger still types
    kb.press(x, y)               # in the host's on_press (when kb.contains)
    kb.drag(x, y)                # in on_drag — the highlight follows
    key = kb.release(x, y)       # in on_release
    # key is one char, or "BACKSPACE" / "SPACE" / "ENTER" / None

    key = kb.key_at(x, y)        # one-shot tap (press + release in place)

Phone-keyboard rules make the keys easy to hit on a 320 px wide panel:
  * every pixel of the keyboard belongs to a key — the gaps and the margins at
    the ends of the short rows count toward the nearest key, so a near miss
    still types;
  * the key under the finger is committed on RELEASE, with a magnified bubble
    showing it while held — slide to correct before lifting;
  * a finger that drifts slightly above the top row still lands on it; one that
    slides well away cancels the press.

Three layers: lowercase letters (with one-shot SHIFT for capitals), numbers +
common symbols, and extra symbols. SHIFT and layer switches are handled
internally and return None.
"""
from __future__ import annotations

import pygame

from musi.player import theme

WIDTH  = 320
ROW_H  = 46                  # touch row pitch (was 34)
HEIGHT = 4 * ROW_H           # 184
CELL_W = 32                  # touch cell of one character key (10 × 32 = 320)
INSET  = 2                   # drawn key = cell shrunk by this on every side
SLOP_ABOVE = 24              # finger this far above the top row still counts
CANCEL_ABOVE = 48            # ...further than this and the press is cancelled

_LAYERS = [
    ["qwertyuiop", "asdfghjkl", "zxcvbnm"],       # 0 — letters (SHIFT = caps)
    ["1234567890", "-/:;()$&@\"", ".,?!'+"],      # 1 — numbers / common symbols
    ["[]{}#%^*+=", "_\\|~<>$&@", ".,?!'\""],      # 2 — extra symbols
]

_KEY_BG     = (40, 40, 56)
_KEY_DOWN   = (78, 78, 100)
_SPECIAL_BG = theme.CARD_BG

# A key: (hit cell, drawn rect, label, value). Hit cells tile the whole area.
_Key = tuple[pygame.Rect, pygame.Rect, str, str]


class Keyboard:
    def __init__(self, top_y: int = 480 - HEIGHT) -> None:
        self.top   = top_y
        self.layer = 0       # index into _LAYERS
        self.shift = False   # one-shot caps on the letters layer
        self._down: str | None = None   # value of the key being held

    @property
    def height(self) -> int:
        return HEIGHT

    def contains(self, x: int, y: int) -> bool:
        return 0 <= x < WIDTH and self.top <= y < self.top + HEIGHT

    # ── key geometry (shared by draw + hit-test) ────────────────────────────────

    def _keys(self) -> list[_Key]:
        """Every key of the current layer; the hit cells cover the full area."""
        rows = _LAYERS[self.layer]
        keys: list[_Key] = []

        def add(x0: int, x1: int, ri: int, label: str, value: str,
                drawn: tuple[int, int] | None = None) -> None:
            """Hit cell x0..x1; ``drawn`` (x0, x1) when the key draws narrower."""
            y = self.top + ri * ROW_H
            cell = pygame.Rect(x0, y, x1 - x0, ROW_H)
            dx0, dx1 = drawn or (x0, x1)
            rect = pygame.Rect(dx0, y, dx1 - dx0, ROW_H).inflate(-2 * INSET,
                                                                 -2 * INSET)
            keys.append((cell, rect, label, value))

        for ri, row in enumerate(rows):
            chars = list(row.upper()) if (self.layer == 0 and self.shift) else list(row)
            span = len(chars) * CELL_W
            x = (WIDTH - span) // 2
            if ri == 2:
                # shift (letters) / symbol page flip (number layers) on the left,
                # backspace on the right — each takes the whole side margin
                label = "" if self.layer == 0 else ("#+=" if self.layer == 1 else "123")
                add(0, x, ri, label, "SHIFT")
            for i, ch in enumerate(chars):
                x0 = x + i * CELL_W
                x1 = x0 + CELL_W
                hx0, hx1 = x0, x1
                if ri != 2:            # short rows: the end keys absorb the margins
                    hx0 = 0 if i == 0 else x0
                    hx1 = WIDTH if i == len(chars) - 1 else x1
                add(hx0, hx1, ri, ch, ch, drawn=(x0, x1))
            if ri == 2:
                add(x + span, WIDTH, ri, "", "BACKSPACE")

        # bottom row: [123/ABC]  [ space ]  [OK]
        add(0, 64, 3, "ABC" if self.layer else "123", "TOGGLE")
        add(64, 256, 3, "space", "SPACE")
        add(256, WIDTH, 3, "", "ENTER")
        return keys

    def _hit(self, x: int, y: int) -> _Key | None:
        if y < self.top - CANCEL_ABOVE or y >= self.top + HEIGHT:
            return None
        if not 0 <= x < WIDTH:
            return None
        y = max(self.top, y)             # just above the top row → top row
        for key in self._keys():
            if key[0].collidepoint(x, y):
                return key
        return None

    # ── interaction ─────────────────────────────────────────────────────────────

    def press(self, x: int, y: int) -> None:
        key = self._hit(x, y)
        self._down = key[3] if key else None

    def drag(self, x: int, y: int) -> None:
        if self._down is None:
            return
        key = self._hit(x, y)
        self._down = key[3] if key else None

    def release(self, x: int, y: int) -> str | None:
        """Commit the key under the finger at lift-off."""
        if self._down is None:
            return None
        key = self._hit(x, y)
        self._down = None
        if key is None:
            return None
        return self._activate(key[3])

    def cancel(self) -> None:
        self._down = None

    def key_at(self, x: int, y: int) -> str | None:
        """A tap: press and release at the same spot."""
        key = self._hit(x, y) if y >= self.top - SLOP_ABOVE else None
        self._down = None
        return self._activate(key[3]) if key else None

    def _activate(self, value: str) -> str | None:
        if value == "TOGGLE":
            self.layer = 1 if self.layer == 0 else 0
            self.shift = False
            return None
        if value == "SHIFT":
            if self.layer == 0:
                self.shift = not self.shift
            else:
                self.layer = 2 if self.layer == 1 else 1
            return None
        if len(value) == 1 and self.layer == 0 and self.shift:
            self.shift = False   # one-shot shift — already uppercased
        return value

    # ── drawing ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, theme.BG, (0, self.top, WIDTH, HEIGHT))
        held: _Key | None = None
        for key in self._keys():
            _cell, rect, label, value = key
            down = (value == self._down)
            if down:
                held = key
            special = value in ("SPACE", "TOGGLE", "ENTER", "SHIFT", "BACKSPACE")
            bg = _SPECIAL_BG if special else _KEY_BG
            if value == "ENTER":
                bg = theme.ACCENT
            elif value == "SHIFT" and self.layer == 0 and self.shift:
                bg = theme.ACCENT
            if down:
                bg = _KEY_DOWN if value != "ENTER" else theme.WHITE
            pygame.draw.rect(surface, bg, rect, border_radius=6)

            fg = theme.ACCENT if (down and value == "ENTER") else theme.WHITE
            if value == "BACKSPACE":
                _draw_backspace(surface, rect.center, fg)
            elif value == "ENTER":
                _draw_check(surface, rect.center, fg)
            elif value == "SHIFT" and self.layer == 0:
                _draw_shift(surface, rect.center, fg)
            else:
                s = theme.render(label, 18 if not special else 13, fg,
                                 bold=special)
                surface.blit(s, s.get_rect(center=rect.center))

        if held is not None and len(held[3]) == 1:
            _draw_bubble(surface, held[1], held[2])


# ── glyph helpers ───────────────────────────────────────────────────────────────

def _draw_bubble(surface, key: pygame.Rect, label: str) -> None:
    """Magnified preview of the held key, rising above it (phone style).
    Plain opaque shapes only — no alpha layers (see blit.py)."""
    w, h = 46, 54
    x = max(2, min(WIDTH - 2 - w, key.centerx - w // 2))
    bubble = pygame.Rect(x, key.y - h + 6, w, h)
    stem = pygame.Rect(key.x, bubble.bottom - 8, key.width, key.bottom - bubble.bottom + 8)
    pygame.draw.rect(surface, theme.ACCENT, bubble.inflate(4, 4), border_radius=11)
    pygame.draw.rect(surface, theme.ACCENT, stem.inflate(4, 4), border_radius=7)
    pygame.draw.rect(surface, _KEY_DOWN, bubble, border_radius=9)
    pygame.draw.rect(surface, _KEY_DOWN, stem, border_radius=6)
    s = theme.render(label, 28, theme.WHITE, bold=True)
    surface.blit(s, s.get_rect(center=(bubble.centerx, bubble.y + h // 2 - 4)))


def _draw_backspace(surface, center, col) -> None:
    cx, cy = center
    pts = [(cx - 10, cy), (cx - 4, cy - 7), (cx + 10, cy - 7),
           (cx + 10, cy + 7), (cx - 4, cy + 7)]
    pygame.draw.polygon(surface, col, pts, 2)
    pygame.draw.line(surface, col, (cx, cy - 3), (cx + 6, cy + 3), 2)
    pygame.draw.line(surface, col, (cx + 6, cy - 3), (cx, cy + 3), 2)


def _draw_check(surface, center, col) -> None:
    cx, cy = center
    pygame.draw.lines(surface, col, False,
                      [(cx - 8, cy), (cx - 2, cy + 7), (cx + 9, cy - 7)], 3)


def _draw_shift(surface, center, col) -> None:
    cx, cy = center
    pygame.draw.polygon(surface, col, [
        (cx, cy - 9), (cx - 8, cy), (cx - 3, cy),
        (cx - 3, cy + 8), (cx + 3, cy + 8), (cx + 3, cy), (cx + 8, cy),
    ])
