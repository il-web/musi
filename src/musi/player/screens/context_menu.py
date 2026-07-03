"""Modal context menu — dim backdrop over the parent screen + option card.

Pushed by list screens on long-press. Options are (label, callback) pairs;
tapping one pops the menu and then runs the callback (so the callback can
push new screens onto a sane stack). Tapping outside the card cancels.
"""
from __future__ import annotations

from typing import Callable

import pygame

from musi.player import theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

CARD_W  = 264
ROW_H   = 52
PAD     = 10
TITLE_H = 40


class ContextMenuScreen(Screen):

    def __init__(self, app, title: str,
                 options: list[tuple[str, Callable[[], None]]]) -> None:
        super().__init__(app)
        self._title   = title
        self._options = options
        self._sel     = -1              # highlighted row (keyboard / flash)
        self._tap     = PendingTap()
        self._dim: pygame.Surface | None = None
        self._card    = self._layout()

    def _layout(self) -> pygame.Rect:
        h = TITLE_H + len(self._options) * ROW_H + PAD * 2
        card = pygame.Rect(0, 0, CARD_W, h)
        card.center = (160, 240)
        return card

    def _row_rect(self, i: int) -> pygame.Rect:
        return pygame.Rect(self._card.x + PAD,
                           self._card.y + TITLE_H + PAD + i * ROW_H,
                           CARD_W - PAD * 2, ROW_H - 6)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        self._tap.update()

        # parent screen underneath, dimmed, so the menu floats over it
        if len(self.app.stack) >= 2:
            self.app.stack[-2].draw(surface, status)
        else:
            surface.fill(theme.BG)
        if self._dim is None:
            self._dim = pygame.Surface((320, 480), pygame.SRCALPHA)
            self._dim.fill((0, 0, 0, 160))
        surface.blit(self._dim, (0, 0))

        # card
        pygame.draw.rect(surface, theme.CARD_BG, self._card, border_radius=12)
        pygame.draw.rect(surface, (55, 55, 75), self._card, 1, border_radius=12)

        # title (track / album name)
        t_s = theme.render(self._title, 12, theme.DIM, bold=True,
                           max_width=CARD_W - PAD * 4)
        surface.blit(t_s, t_s.get_rect(centerx=160, y=self._card.y + 14))

        # option rows
        for i, (label, _cb) in enumerate(self._options):
            r   = self._row_rect(i)
            sel = (i == self._sel)
            pygame.draw.rect(surface, theme.ACCENT if sel else (36, 36, 52),
                             r, border_radius=8)
            l_s = theme.render(label, 14, theme.WHITE, bold=sel,
                               max_width=r.w - 20)
            surface.blit(l_s, l_s.get_rect(centerx=160, centery=r.centery))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if self._tap.pending:
            return None
        for i in range(len(self._options)):
            if self._row_rect(i).collidepoint(x, y):
                self._sel = i
                self._tap.set(lambda i=i: self._run(i))
                return None
        if not self._card.collidepoint(x, y):
            self.app.pop()                       # tap outside = cancel
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = (self._sel - 1) % len(self._options)
        elif button == Button.DOWN:
            self._sel = (self._sel + 1) % len(self._options)
        elif button == Button.SELECT and self._sel >= 0:
            self._run(self._sel)
        elif button == Button.BACK:
            self.app.pop()

    def _run(self, i: int) -> None:
        cb = self._options[i][1]
        self.app.pop()
        cb()
