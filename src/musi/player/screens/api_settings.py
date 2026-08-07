"""Settings → API screen — device API token, server URL and service state.

The token gates every route except the page at "/" itself. It is read off
this screen and typed into http://musi.local:8080 — hence the short format.
Regenerating takes effect immediately: the server re-reads the token file on
each request, so no service restart is needed.
"""
from __future__ import annotations

import socket
import threading
import time

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

PORT = 8080          # musi.api.server.PORT (kept local: no Flask import in the UI)
_PROBE_EVERY = 3.0

_REGEN_RECT = pygame.Rect(10, 330, 300, 52)


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?.?.?.?"


class ApiSettingsScreen(Screen):
    animates = True   # live service-state dot

    def __init__(self, app) -> None:
        super().__init__(app)
        self._token:   str = ""
        self._ip:      str = ""
        self._running: bool = False
        self._stop = threading.Event()
        self._enter_t: float = 0.0
        self._nav_surf: pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._enter_t = time.monotonic()
        self._ip = _local_ip()
        from musi.api import auth
        self._token = auth.load_token()
        self._stop.clear()
        threading.Thread(target=self._probe_loop, daemon=True).start()

    def on_exit(self) -> None:
        self._stop.set()

    def _probe_loop(self) -> None:
        while not self._stop.is_set():
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
                s.close()
                self._running = True
            except OSError:
                self._running = False
            self._stop.wait(_PROBE_EVERY)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if _REGEN_RECT.collidepoint(x, y):
            self._confirm_regenerate()
            return None
        return super().handle_touch(x, y)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.SELECT:
            self._confirm_regenerate()
        elif button == Button.BACK:
            self.app.pop()

    def _confirm_regenerate(self) -> None:
        from musi.player.screens.context_menu import ContextMenuScreen

        def do_regen() -> None:
            from musi.api import auth
            self._token = auth.regenerate_token()

        self.app.push(ContextMenuScreen(
            self.app, "New token? Browsers must re-enter it", [
                ("Regenerate", do_regen),
                ("Cancel",     lambda: None),
            ]))

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf = theme.render("Enter = regenerate   Esc = back", 10, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        header = theme.render("API", 16, theme.WHITE, bold=True)
        surface.blit(header, (14, 26))

        # ── server card ───────────────────────────────────────────────────────
        label = theme.render("SERVER", 9, theme.DIM, bold=True)
        surface.blit(label, (14, 66))
        pygame.draw.rect(surface, theme.CARD_BG,
                         pygame.Rect(10, 82, 300, 74), border_radius=8)
        url_s = theme.render(f"http://{self._ip}:{PORT}", 13, theme.ACCENT,
                             bold=True, max_width=280)
        surface.blit(url_s, (24, 94))
        if self._running:
            t     = time.monotonic() - self._enter_t
            alpha = int(160 + 95 * (0.5 + 0.5 * __import__('math').sin(t * 2.5)))
            dot_c = tuple(int(c * alpha / 255) for c in theme.ACCENT)
            pygame.draw.circle(surface, dot_c, (28, 132), 4)
            state_s = theme.render("service running", 10, theme.DIM)
        else:
            pygame.draw.circle(surface, (220, 120, 120), (28, 132), 4)
            state_s = theme.render("service not running", 10, (220, 120, 120))
        surface.blit(state_s, (38, 126))

        # ── token card ────────────────────────────────────────────────────────
        label = theme.render("ACCESS TOKEN", 9, theme.DIM, bold=True)
        surface.blit(label, (14, 176))
        pygame.draw.rect(surface, theme.CARD_BG,
                         pygame.Rect(10, 192, 300, 78), border_radius=8)
        # The token is 8 chars shown as XXXX-XXXX — it fits on one line, so set
        # it large and centred. This is read off the screen and typed by hand on
        # a phone, so legibility is the whole job of this card.
        token_s = theme.render(self._token, 26, theme.WHITE, bold=True,
                               max_width=280)
        surface.blit(token_s, token_s.get_rect(centerx=160, centery=231))

        hint = theme.render("Enter this at musi.local:8080", 10, theme.DIM)
        surface.blit(hint, hint.get_rect(centerx=160, y=282))

        # ── regenerate button ─────────────────────────────────────────────────
        pygame.draw.rect(surface, theme.CARD_BG, _REGEN_RECT, border_radius=8)
        pygame.draw.rect(surface, theme.ACCENT, _REGEN_RECT, width=1, border_radius=8)
        regen_s = theme.render("Regenerate token", 13, theme.ACCENT, bold=True)
        surface.blit(regen_s, regen_s.get_rect(center=_REGEN_RECT.center))
        warn = theme.render("Old token stops working immediately", 9, theme.DIM)
        surface.blit(warn, warn.get_rect(centerx=160, y=390))

        surface.blit(self._nav_surf, self._nav_surf.get_rect(centerx=160, y=456))
