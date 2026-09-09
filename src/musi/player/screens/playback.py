"""Playback settings — currently just crossfade.

Modelled on screens/customization.py: a header, a column of options, tap to
apply. Unlike the wallpaper picker this also has to tell MPD, because the
setting lives in MPD's state file rather than being read back from prefs on
every frame.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, minibar, prefs, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

# Seconds MPD blends over when crossfade is on. Zero is how MPD spells "off",
# so the pref is a bool and this is the only place the duration is named.
CROSSFADE_S = 2

OPTIONS: list[tuple[bool, str]] = [
    (False, "Off"),
    (True,  "On"),
]

ROW_X, ROW_W = 10, 300
ROW_H        = 56
ROW_Y        = 132
ROW_GAP      = 10


def row_rect(i: int) -> pygame.Rect:
    """Screen rect of option i."""
    return pygame.Rect(ROW_X, ROW_Y + i * (ROW_H + ROW_GAP), ROW_W, ROW_H)


def _draw_check(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    """Tick mark, in the line-segment style of icons.py."""
    pts = [(cx - 6, cy), (cx - 2, cy + 5), (cx + 7, cy - 6)]
    pygame.draw.lines(surface, col, False, pts, 3)


class PlaybackScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._tap = PendingTap()
        self._header: pygame.Surface | None = None
        self._hint:   pygame.Surface | None = None
        self._labels: list[pygame.Surface] = []

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header is None:
            self._header = theme.render("Playback", 16, theme.WHITE, bold=True)
            self._hint = theme.render(
                f"Crossfade — blend tracks over {CROSSFADE_S}s", 12, theme.DIM)
            self._labels = [theme.render(label, 16, theme.WHITE)
                            for _, label in OPTIONS]

        self._tap.update()
        current = bool(prefs.get("crossfade"))

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(self._header, (14, 34))
        surface.blit(self._hint, (14, 78))

        for i, (value, _) in enumerate(OPTIONS):
            rect = row_rect(i)
            selected = value == current
            bg = theme.ACCENT if selected else theme.CARD_BG
            pygame.draw.rect(surface, bg, rect, border_radius=8)

            label = self._labels[i] if selected else theme.render(
                OPTIONS[i][1], 16, theme.DIM)
            surface.blit(label, (28, rect.centery - label.get_height() // 2))

            if selected:
                _draw_check(surface, rect.right - 26, rect.centery, theme.WHITE)

        minibar.draw(surface, self.app, status)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return None

        if not self._tap.pending:
            for i, (value, _) in enumerate(OPTIONS):
                if row_rect(i).collidepoint(x, y):
                    self._tap.set(lambda v=value: self._apply(v))
                    return None
        return super().handle_touch(x, y)

    # ── apply ─────────────────────────────────────────────────────────────────

    def _apply(self, on: bool) -> None:
        prefs.set("crossfade", on)
        self.app.mpd.set_crossfade(CROSSFADE_S if on else 0)
