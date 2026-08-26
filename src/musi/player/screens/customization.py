"""Customization app — pick the home screen's wallpaper.

Modelled on screens/sleep.py: a header, a row of options, tap to apply. The
choice is written straight to prefs, and the launcher reads it on its next
frame, so there is nothing to invalidate here.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, minibar, prefs, statusbar, theme, wallpaper
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

OPTIONS: list[tuple[str, str]] = [
    ("none", "None"),
    ("warm", "Warm"),
    ("cool", "Cool"),
]

TILE_W, TILE_H = 84, 108
TILE_Y = 120
GAP    = (320 - 3 * TILE_W) // 4          # 17px, evenly spread
LABEL_Y = TILE_Y + TILE_H + 10


def tile_rect(i: int) -> pygame.Rect:
    """Screen rect of option i."""
    return pygame.Rect(GAP + i * (TILE_W + GAP), TILE_Y, TILE_W, TILE_H)


class CustomizationScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._tap = PendingTap()
        self._header: pygame.Surface | None = None
        self._labels: list[pygame.Surface] = []

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header is None:
            self._header = theme.render("Customization", 16, theme.WHITE,
                                        bold=True)
            self._labels = [theme.render(label, 12, theme.DIM)
                            for _, label in OPTIONS]

        self._tap.update()
        current = str(prefs.get("wallpaper"))

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._header, (14, 34))

        hint = theme.render("Home screen wallpaper", 12, theme.DIM)
        surface.blit(hint, (14, 78))

        for i, (name, _) in enumerate(OPTIONS):
            rect = tile_rect(i)
            thumb = wallpaper.thumbnail(name, (TILE_W, TILE_H))
            if thumb is not None:
                surface.blit(thumb, rect.topleft)
            else:
                pygame.draw.rect(surface, theme.CARD_BG, rect, border_radius=8)

            if name == current:
                pygame.draw.rect(surface, theme.ACCENT, rect.inflate(6, 6), 3,
                                 border_radius=10)

            label = self._labels[i]
            surface.blit(label, label.get_rect(centerx=rect.centerx, y=LABEL_Y))

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

        if not self._tap.pending:
            for i, (name, _) in enumerate(OPTIONS):
                if tile_rect(i).inflate(GAP, 20).collidepoint(x, y):
                    self._tap.set(lambda n=name: prefs.set("wallpaper", n))
                    return None
        return super().handle_touch(x, y)
