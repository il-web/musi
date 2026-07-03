"""WiFi Transfer screen — starts the HTTP upload server and shows the URL."""
from __future__ import annotations

import socket
import time

import pygame

from musi.player import audio_detect, hardening, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.wifi_transfer.server import PORT, WifiTransferServer


def _local_ip() -> str:
    """Best-effort: get the LAN IP this device is reachable on."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?.?.?.?"


class USBScreen(Screen):   # keep class name so home.py import still works
    animates = True   # transfer screen — stay awake while files come in

    def __init__(self, app) -> None:
        super().__init__(app)
        self._server:   WifiTransferServer | None = None
        self._ip:       str   = ""
        self._error:    str   = ""
        self._locked:   bool  = False
        self._enter_t:  float = 0.0

        # static surfaces (lazy)
        self._nav_surf: pygame.Surface | None = None
        self._url_surf: pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._enter_t = time.monotonic()
        self._error   = ""
        self._ip      = _local_ip()

        # Storage locked → uploads would only land in the RAM overlay (and can
        # fill it); refuse to start the server and point at the unlock.
        self._locked = hardening.overlay_active()
        if self._locked:
            self._server = None
            return

        hardening.wifi_powersave(False)   # full-speed uploads while we're open

        from musi.library.config import art_dir, db_path, music_root
        try:
            self._server = WifiTransferServer(
                music_root = music_root(),
                db_path    = db_path(),
                art_dir    = art_dir(),
            )
            self._server.start()
        except Exception as exc:
            self._error  = str(exc)
            self._server = None

        # Invalidate URL surface so it rebuilds with fresh IP
        self._url_surf = None

    def on_exit(self) -> None:
        if self._server:
            self._server.stop()
            self._server = None
        if not self._locked:
            hardening.wifi_powersave(True)   # back to the battery-friendly default

    # ── input ─────────────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            self.app.pop()

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf = theme.render("Esc = stop & go back", 10, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        if self._locked:
            self._draw_locked(surface)
        elif self._error:
            self._draw_error(surface)
        else:
            self._draw_running(surface)

        surface.blit(self._nav_surf,
                     self._nav_surf.get_rect(centerx=160, y=456))

    def _draw_running(self, surface: pygame.Surface) -> None:
        # ── WiFi icon ─────────────────────────────────────────────────────────
        _wifi_icon(surface, 160, 148, theme.ACCENT)

        # ── title ─────────────────────────────────────────────────────────────
        title = theme.render("WiFi Transfer", 18, theme.WHITE, bold=True)
        surface.blit(title, title.get_rect(centerx=160, y=190))

        # ── "open in browser" hint ────────────────────────────────────────────
        hint = theme.render("Open in your browser:", 11, theme.DIM)
        surface.blit(hint, hint.get_rect(centerx=160, y=222))

        # ── URL card ──────────────────────────────────────────────────────────
        url = f"http://{self._ip}:{PORT}"
        pygame.draw.rect(surface, theme.CARD_BG,
                         pygame.Rect(12, 244, 296, 42), border_radius=8)
        url_s = theme.render(url, 14, theme.ACCENT, bold=True, max_width=284)
        surface.blit(url_s, url_s.get_rect(centerx=160, centery=265))

        # ── mDNS alias ────────────────────────────────────────────────────────
        mdns_s = theme.render(f"or  http://musi.local:{PORT}", 10, theme.DIM)
        surface.blit(mdns_s, mdns_s.get_rect(centerx=160, y=296))

        # ── separator ─────────────────────────────────────────────────────────
        pygame.draw.line(surface, (30, 30, 44), (14, 320), (306, 320), 1)

        # ── upload counter ────────────────────────────────────────────────────
        n = self._server.uploaded if self._server else 0
        if n == 0:
            cnt_s = theme.render("Waiting for uploads…", 11, theme.DIM)
        else:
            cnt_s = theme.render(
                f"✓  {n} file{'s' if n != 1 else ''} uploaded this session",
                11, (80, 200, 120),
            )
        surface.blit(cnt_s, cnt_s.get_rect(centerx=160, y=334))

        # ── pulsing dot (server alive indicator) ──────────────────────────────
        t      = time.monotonic() - self._enter_t
        alpha  = int(160 + 95 * (0.5 + 0.5 * __import__('math').sin(t * 2.5)))
        dot_c  = tuple(int(c * alpha / 255) for c in theme.ACCENT)
        pygame.draw.circle(surface, dot_c, (20, 194), 4)
        live_s = theme.render("server running", 9, theme.DIM)
        surface.blit(live_s, (28, 190))

    def _draw_locked(self, surface: pygame.Surface) -> None:
        _wifi_icon(surface, 160, 148, theme.DIM)
        title = theme.render("Storage is locked", 16, theme.WHITE, bold=True)
        surface.blit(title, title.get_rect(centerx=160, y=196))
        for i, line in enumerate((
            "Uploads can't be saved while the SD card",
            "is read-only. Unlock in Settings → Power,",
            "then reboot and try again.",
        )):
            s = theme.render(line, 11, theme.DIM)
            surface.blit(s, s.get_rect(centerx=160, y=232 + i * 18))

    def _draw_error(self, surface: pygame.Surface) -> None:
        _wifi_icon(surface, 160, 186, theme.DIM)
        err_title = theme.render("Could not start server", 14, theme.WHITE, bold=True)
        surface.blit(err_title, err_title.get_rect(centerx=160, y=236))
        err_s = theme.render(self._error, 11, theme.DIM, max_width=296)
        surface.blit(err_s, err_s.get_rect(centerx=160, y=264))


# ── drawing helpers ───────────────────────────────────────────────────────────

def _wifi_icon(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    import math
    for r in (28, 18, 8):
        pts = [
            (cx + int(r * math.cos(math.pi * (0.5 + 0.45 * t / 20))),
             cy + 4  - int(r * math.sin(math.pi * (0.5 + 0.45 * t / 20))))
            for t in range(-20, 21)
        ]
        pygame.draw.lines(surface, col, False, pts, 2)
    pygame.draw.circle(surface, col, (cx, cy + 4), 4)
