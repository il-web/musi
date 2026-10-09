"""Crash log viewer — Settings → Updates → the "Last crash" line.

Shows player/crashguard.py's crash.log, newest crash first, as plain wrapped
lines you can scroll. Monospace isn't available on every image, so long
traceback lines wrap at word boundaries instead.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, crashguard, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import KineticList, draw_scrollbar

TOP    = 64
BOTTOM = 470
LINE_H = 15
SIZE   = 10


def log_rows(text: str, max_w: int = 292) -> list[tuple[str, bool]]:
    """(row, is_header) rows, newest crash first."""
    entries = [e for e in text.split("=== ") if e.strip()]
    rows: list[tuple[str, bool]] = []
    for entry in reversed(entries):
        head, _, body = entry.partition("\n")
        rows.append((head.rstrip(" ="), True))
        for line in body.splitlines():
            if not line.strip():
                continue
            rows.extend((r, False) for r in theme.wrap(line.strip(), SIZE, False, max_w))
        rows.append(("", False))
    return rows


class CrashLogScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._rows: list[tuple[str, bool]] = []
        self._klist = KineticList(LINE_H, BOTTOM - TOP)

    def on_enter(self) -> None:
        self._rows = log_rows(crashguard.read_log()) or [("No crashes recorded.", False)]
        self._klist.set_count(len(self._rows), reset=True)

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(theme.render("Crash log", 16, theme.WHITE, bold=True), (14, 30))

        self._klist.update()
        first, shift = self._klist.first_visible(), self._klist.pixel_shift()
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, TOP, 320, BOTTOM - TOP))
        for vi in range(self._klist.visible_rows()):
            i = first + vi
            if i >= len(self._rows):
                break
            text, header = self._rows[i]
            if text:
                s = theme.render(text, SIZE, theme.ACCENT if header else theme.DIM,
                                 bold=header, max_width=296)
                surface.blit(s, (14, TOP + vi * LINE_H - shift))
        surface.set_clip(clip)
        draw_scrollbar(surface, 314, TOP, BOTTOM - TOP, self._klist)

    def handle_scroll(self, dy: float) -> None:
        self._klist.scroll_by(dy)

    def handle_scroll_start(self) -> None:
        self._klist.start_touch()

    def handle_scroll_end(self) -> None:
        self._klist.end_touch()

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._klist.scroll_by(LINE_H * 4)
        elif button == Button.DOWN:
            self._klist.scroll_by(-LINE_H * 4)
        else:
            super().handle(button, status)
