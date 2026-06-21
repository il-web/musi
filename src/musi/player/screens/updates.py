"""Software Update screen — check GitHub and pull the latest version.

Shows the current vs latest commit and an update count. Tap "Check" to re-query
the remote; tap "Update now" (enabled only when behind) to pull + restart.
"""
from __future__ import annotations

import threading

import pygame

from musi.player import audio_detect, statusbar, theme, updater
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

CHECK_RECT  = pygame.Rect(20, 372, 130, 52)
UPDATE_RECT = pygame.Rect(170, 372, 130, 52)


class UpdatesScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._status: updater.UpdateStatus | None = None
        self._busy:   bool = False
        self._msg:    str  = ""
        self._hdr:    pygame.Surface | None = None

    def on_enter(self) -> None:
        # Show the current version immediately; check the remote in the background.
        self._status = updater.UpdateStatus(current=updater.current_version())
        self._check()

    # ── async actions ───────────────────────────────────────────────────────────

    def _check(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._msg  = "Checking…"

        def work() -> None:
            self._status = updater.check()
            self._msg    = ""
            self._busy   = False

        threading.Thread(target=work, daemon=True).start()

    def _update(self) -> None:
        if self._busy or not (self._status and self._status.available):
            return
        self._busy = True
        self._msg  = "Updating… do not power off"

        def work() -> None:
            ok, message = updater.apply()      # on success this restarts the app
            self._msg  = message if ok else f"Failed: {message}"
            self._busy = False

        threading.Thread(target=work, daemon=True).start()

    # ── draw ────────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr = theme.render("Updates", 16, theme.WHITE, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._hdr, (14, 26))

        st = self._status
        cur = st.current if st else "?"
        lat = st.latest  if st else "?"

        # version rows
        self._row(surface, 78,  "Current", cur, theme.WHITE)
        self._row(surface, 116, "Latest",  lat, theme.WHITE)

        # status line
        if st and st.error:
            line, col = st.error, (230, 120, 120)
        elif st and st.available:
            n = st.behind
            line, col = f"● Update available ({n} commit{'s' if n != 1 else ''})", theme.ACCENT
        elif st and st.is_repo:
            line, col = "Up to date", (120, 210, 140)
        else:
            line, col = "—", theme.DIM
        s = theme.render(line, 13, col, max_width=300)
        surface.blit(s, s.get_rect(centerx=160, y=176))

        if self._msg:
            m = theme.render(self._msg, 12, theme.WHITE, max_width=300)
            surface.blit(m, m.get_rect(centerx=160, y=210))

        # buttons
        self._button(surface, CHECK_RECT, "Check", enabled=not self._busy)
        can_update = bool(st and st.available) and not self._busy
        self._button(surface, UPDATE_RECT, "Update now", enabled=can_update, accent=can_update)

    def _row(self, surface, y, label, value, col):
        l = theme.render(label, 12, theme.DIM)
        surface.blit(l, (24, y))
        v = theme.render(value, 14, col, bold=True)
        surface.blit(v, (140, y - 2))

    def _button(self, surface, rect, label, enabled, accent=False):
        if accent and enabled:
            bg, fg = theme.ACCENT, theme.WHITE
        elif enabled:
            bg, fg = theme.CARD_BG, theme.WHITE
        else:
            bg, fg = (24, 24, 32), (90, 90, 105)
        pygame.draw.rect(surface, bg, rect, border_radius=10)
        s = theme.render(label, 13, fg, bold=True)
        surface.blit(s, s.get_rect(center=rect.center))

    # ── input ────────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.BACK
        if CHECK_RECT.collidepoint(x, y):
            self._check()
            return None
        if UPDATE_RECT.collidepoint(x, y):
            self._update()
            return None
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            self.app.pop()
        elif button == Button.SELECT:
            self._update()
