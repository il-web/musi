"""Sleep app — pick a duration, then playback pauses when it elapses.

Wraps App.set_sleep_timer / App.sleep_remaining, which already do the work
(app.py:107, app.py:114). This screen replaces the old Settings context menu.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

TOP    = 120      # top of the first option row
ROW_H  = 56
STAT_Y = 78       # the "Off" / "40 min left" line under the header


def row_y(i: int) -> int:
    """Top y of option row i."""
    return TOP + i * ROW_H


def format_remaining(seconds: float | None) -> str:
    """'Off' or '41 min left' — minutes always round up so it never reads 0."""
    if seconds is None:
        return "Off"
    return f"{int(seconds // 60) + 1} min left"


class SleepScreen(Screen):

    OPTIONS: list[tuple[str, int | None]] = [
        ("Off",    None),
        ("15 min", 15),
        ("30 min", 30),
        ("60 min", 60),
        ("90 min", 90),
    ]

    def __init__(self, app) -> None:
        super().__init__(app)
        self._tap = PendingTap()
        self._status_text = ""
        self._header_surf: pygame.Surface | None = None
        self._opt_surfs:   list[pygame.Surface] = []
        self._stat_surf:   pygame.Surface | None = None

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header_surf is None:
            self._header_surf = theme.render("Sleep", 16, theme.WHITE, bold=True)
            self._opt_surfs   = [theme.render(l, 16, theme.WHITE)
                                 for l, _ in self.OPTIONS]

        self._tap.update()

        text = format_remaining(self.app.sleep_remaining())
        if text != self._status_text:
            self._status_text = text
            self._stat_surf   = theme.render(text, 13, theme.ACCENT)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._header_surf, (14, 34))
        surface.blit(self._stat_surf, (14, STAT_Y))

        armed = self.app.sleep_remaining() is not None
        for i, (_, minutes) in enumerate(self.OPTIONS):
            y = row_y(i)
            rect = pygame.Rect(10, y, 300, ROW_H - 6)
            selected = (minutes is None and not armed)
            pygame.draw.rect(surface, theme.ACCENT if selected else theme.CARD_BG,
                             rect, border_radius=8)
            surf = self._opt_surfs[i]
            surface.blit(surf, surf.get_rect(
                x=28, centery=y + (ROW_H - 6) // 2))

        minibar.draw(surface, self.app, status)

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return None

        if TOP <= y < row_y(len(self.OPTIONS)) and not self._tap.pending:
            i = (y - TOP) // ROW_H
            if 0 <= i < len(self.OPTIONS):
                minutes = self.OPTIONS[i][1]
                self._tap.set(lambda: self.app.set_sleep_timer(minutes))
                return None
        return super().handle_touch(x, y)
