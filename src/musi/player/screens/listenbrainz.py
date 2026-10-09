"""ListenBrainz sign-in — Settings → Playback → ListenBrainz.

One field: the user token from listenbrainz.org/settings. It's checked with
the API before it is saved. A 36-character token is a lot for the on-screen
keyboard, so the same can be done from a phone: PUT /api/v1/listenbrainz.
"""
from __future__ import annotations

import threading

import pygame

from musi.library import listenbrainz
from musi.player import audio_detect, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

ACTION  = pygame.Rect(30, 250, 260, 56)
SIGNOUT = pygame.Rect(90, 320, 140, 34)

_INFO = (
    "Every song you play counts as a listen once",
    "you've heard half of it (or 4 minutes).",
    "Plays made offline are sent later.",
)


class ListenBrainzScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self.saved = listenbrainz.load_settings()
        self.checking = False
        self.error = ""

    @property
    def animates(self) -> bool:
        return self.checking

    def summary(self) -> tuple[str, tuple]:
        if self.checking:
            return "Checking token…", theme.ACCENT
        if self.error:
            return f"Failed: {self.error}", (230, 110, 110)
        if not self.saved:
            return "Not connected", theme.DIM
        n = listenbrainz.queued()
        tail = f" · {n} waiting to send" if n else ""
        return f"Scrobbling as {self.saved.get('user', '?')}{tail}", theme.ACCENT

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(theme.render("ListenBrainz", 16, theme.WHITE, bold=True), (14, 30))
        text, col = self.summary()
        surface.blit(theme.render(text, 12, col, max_width=292), (14, 62))
        for i, line in enumerate(_INFO):
            surface.blit(theme.render(line, 11, theme.DIM, max_width=292), (14, 104 + i * 18))
        surface.blit(theme.render("Token: listenbrainz.org → Settings → User token",
                                  10, theme.DIM, max_width=292), (14, 172))
        surface.blit(theme.render("Or from your phone: PUT /api/v1/listenbrainz",
                                  10, theme.DIM, max_width=292), (14, 190))

        enabled = not self.checking
        pygame.draw.rect(surface, theme.ACCENT if enabled else theme.CARD_BG,
                         ACTION, border_radius=12)
        label = "Change token" if self.saved else "Enter token"
        s = theme.render(label, 16, theme.WHITE if enabled else theme.DIM, bold=True)
        surface.blit(s, s.get_rect(center=ACTION.center))
        if self.saved:
            so = theme.render("Sign out", 12, theme.DIM)
            surface.blit(so, so.get_rect(center=SIGNOUT.center))
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
        if ACTION.collidepoint(x, y) and not self.checking:
            self._enter_token()
            return None
        if self.saved and SIGNOUT.collidepoint(x, y):
            listenbrainz.clear_settings()
            self.saved = None
            return None
        return super().handle_touch(x, y)

    def _enter_token(self) -> None:
        from musi.player.screens.text_entry import TextEntryScreen
        self.app.push(TextEntryScreen(self.app, "ListenBrainz token",
                                      on_commit=self.check_token, max_len=64))

    def check_token(self, token: str) -> None:
        """Validate with the API on a worker thread; save only a good token."""
        token = token.strip()
        self.checking, self.error = True, ""

        def work() -> None:
            try:
                user = listenbrainz.validate_token(token)
                listenbrainz.save_settings(token, user)
                self.saved = listenbrainz.load_settings()
            except listenbrainz.ListenBrainzError as exc:
                self.error = str(exc)
            except OSError as exc:
                self.error = f"could not save ({exc})"
            finally:
                self.checking = False

        threading.Thread(target=work, daemon=True).start()

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.SELECT and not self.checking:
            self._enter_token()
        else:
            super().handle(button, status)
