"""Reusable single-line text prompt with the on-screen keyboard.

    self.app.push(TextEntryScreen(app, "New playlist", on_commit=make_it))

``on_commit`` is called with the trimmed text when the user taps OK / presses
Enter; an empty field does nothing. Backing out (edge swipe or Back) cancels
without calling it. A hardware USB keyboard also types, like the Search screen.
"""
from __future__ import annotations

import time
from typing import Callable

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.keyboard import Keyboard
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

KB_TOP  = 318
BOX_Y   = 92
BOX_H   = 42
_BLINK  = 0.55          # seconds per cursor blink half-cycle


class TextEntryScreen(Screen):
    animates = True      # cursor blink — stay responsive, never sleep

    def __init__(self, app, title: str, *, initial: str = "",
                 on_commit: Callable[[str], None], max_len: int = 40) -> None:
        super().__init__(app)
        self._title     = title
        self._text      = initial
        self._on_commit = on_commit
        self._max_len   = max_len
        self._kb        = Keyboard(KB_TOP)
        self._enter_t   = time.monotonic()
        self._title_surf: pygame.Surface | None = None

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_RETURN:
            self._commit()
            return True
        if event.key == pygame.K_BACKSPACE:
            if self._text:
                self._text = self._text[:-1]
                return True
            return False                       # empty → let Back pop the screen
        if event.unicode and event.unicode.isprintable():
            self._append(event.unicode)
            return True
        return False

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < statusbar.BAR_H:
            return Button.HOME
        if y >= KB_TOP:
            self._on_key(self._kb.key_at(x, y))
            return None
        return None

    def _on_key(self, key: "str | None") -> None:
        if key is None:
            return
        if key == "ENTER":
            self._commit()
        elif key == "BACKSPACE":
            self._text = self._text[:-1]
        elif key == "SPACE":
            self._append(" ")
        elif len(key) == 1:
            self._append(key)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            if self._text:
                self._text = self._text[:-1]
            else:
                self.app.pop()
        elif button in (Button.SELECT, Button.PLAY_PAUSE):
            self._commit()

    def _append(self, ch: str) -> None:
        if len(self._text) < self._max_len:
            self._text += ch
            self._enter_t = time.monotonic()

    def _commit(self) -> None:
        text = self._text.strip()
        if not text:
            return
        self.app.pop()
        self._on_commit(text)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._title_surf is None:
            self._title_surf = theme.render(self._title, 14, theme.WHITE,
                                            bold=True, max_width=296)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)

        surface.blit(self._title_surf,
                     self._title_surf.get_rect(centerx=160, y=60))

        box = pygame.Rect(8, BOX_Y, 304, BOX_H)
        pygame.draw.rect(surface, (28, 28, 42), box, border_radius=6)
        pygame.draw.rect(surface, theme.ACCENT, box, 1, border_radius=6)

        cursor = "|" if int((time.monotonic() - self._enter_t) / _BLINK) % 2 == 0 else " "
        txt = theme.render(self._text + cursor, 14, theme.WHITE, max_width=288)
        surface.blit(txt, (18, box.y + (BOX_H - txt.get_height()) // 2))

        hint = theme.render("OK = save   ·   tap top bar = cancel", 10, theme.DIM)
        surface.blit(hint, hint.get_rect(centerx=160, y=BOX_Y + BOX_H + 12))

        self._kb.draw(surface)
