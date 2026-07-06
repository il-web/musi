"""WiFi Transfer screen — info page for the always-on device API server.

The upload server no longer starts/stops with this screen: musi-api.service
runs it permanently on port 8080 (see musi.api). This screen just shows the
URL + QR code for the upload page and whether the service is reachable.
"""
from __future__ import annotations

import socket
import threading
import time

import pygame

from musi.player import audio_detect, hardening, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

PORT = 8080          # musi.api.server.PORT (kept local: no Flask import in the UI)
_PROBE_EVERY = 3.0   # seconds between service probes


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


def _qr_surface(text: str, target_px: int = 118) -> "pygame.Surface | None":
    """Render a QR code for ``text``; None if segno isn't installed."""
    try:
        import segno
    except ImportError:
        return None
    matrix = [bytes(row) for row in segno.make(text, error="m").matrix]
    n     = len(matrix)
    quiet = 2                                   # quiet-zone modules per side
    scale = max(2, target_px // (n + quiet * 2))
    size  = (n + quiet * 2) * scale
    surf  = pygame.Surface((size, size))
    surf.fill((255, 255, 255))
    for y, row in enumerate(matrix):
        for x, v in enumerate(row):
            if v:
                pygame.draw.rect(
                    surf, (0, 0, 0),
                    ((quiet + x) * scale, (quiet + y) * scale, scale, scale),
                )
    return surf


class USBScreen(Screen):   # keep class name so home.py import still works
    animates = True   # live status dot + service probe

    def __init__(self, app) -> None:
        super().__init__(app)
        self._ip:      str  = ""
        self._locked:  bool = False
        self._enter_t: float = 0.0

        # service probe (background thread — keep sockets out of the draw loop)
        self._running: bool = False
        self._tracks:  "int | None" = None
        self._stop = threading.Event()
        self._probe_thread: threading.Thread | None = None

        self._qr_surf:  pygame.Surface | None = None
        self._nav_surf: pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._enter_t = time.monotonic()
        self._ip      = _local_ip()
        self._locked  = hardening.overlay_active()
        self._qr_surf = _qr_surface(f"http://{self._ip}:{PORT}")

        if not self._locked:
            hardening.wifi_powersave(False)   # full-speed uploads while we're open

        self._stop.clear()
        self._probe_thread = threading.Thread(target=self._probe_loop, daemon=True)
        self._probe_thread.start()

    def on_exit(self) -> None:
        self._stop.set()
        if not self._locked:
            hardening.wifi_powersave(True)   # back to the battery-friendly default

    def _probe_loop(self) -> None:
        while not self._stop.is_set():
            try:
                import json
                import urllib.request
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/stats", timeout=2
                ) as r:
                    self._tracks = json.load(r).get("tracks")
                self._running = True
            except Exception:
                self._running = False
                self._tracks  = None
            self._stop.wait(_PROBE_EVERY)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            self.app.pop()

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf = theme.render("Esc = back", 10, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        if self._locked:
            self._draw_locked(surface)
        else:
            self._draw_info(surface)

        surface.blit(self._nav_surf,
                     self._nav_surf.get_rect(centerx=160, y=456))

    def _draw_info(self, surface: pygame.Surface) -> None:
        title = theme.render("WiFi Transfer", 18, theme.WHITE, bold=True)
        surface.blit(title, title.get_rect(centerx=160, y=40))

        # ── URL card ──────────────────────────────────────────────────────────
        url = f"http://{self._ip}:{PORT}"
        pygame.draw.rect(surface, theme.CARD_BG,
                         pygame.Rect(12, 76, 296, 42), border_radius=8)
        url_s = theme.render(url, 14, theme.ACCENT, bold=True, max_width=284)
        surface.blit(url_s, url_s.get_rect(centerx=160, centery=97))

        mdns_s = theme.render(f"or  http://musi.local:{PORT}", 10, theme.DIM)
        surface.blit(mdns_s, mdns_s.get_rect(centerx=160, y=126))

        # ── QR code (scan with a phone) ───────────────────────────────────────
        if self._qr_surf:
            surface.blit(self._qr_surf,
                         self._qr_surf.get_rect(centerx=160, y=156))
            qr_hint = theme.render("Scan to open the upload page", 10, theme.DIM)
            surface.blit(qr_hint, qr_hint.get_rect(
                centerx=160, y=160 + self._qr_surf.get_height()))
        else:
            hint = theme.render("Open the URL in your browser", 11, theme.DIM)
            surface.blit(hint, hint.get_rect(centerx=160, y=200))

        # ── service state ─────────────────────────────────────────────────────
        y_state = 402
        if self._running:
            t     = time.monotonic() - self._enter_t
            alpha = int(160 + 95 * (0.5 + 0.5 * __import__('math').sin(t * 2.5)))
            dot_c = tuple(int(c * alpha / 255) for c in theme.ACCENT)
            label = "server running"
            if self._tracks is not None:
                label += f"  ·  {self._tracks} tracks in library"
            state_s = theme.render(label, 10, theme.DIM)
            x0 = 160 - (state_s.get_width() + 12) // 2
            pygame.draw.circle(surface, dot_c, (x0 + 4, y_state + 6), 4)
            surface.blit(state_s, (x0 + 12, y_state))
        else:
            state_s = theme.render("server not reachable — try Settings → API", 10, (220, 120, 120))
            surface.blit(state_s, state_s.get_rect(centerx=160, y=y_state))

    def _draw_locked(self, surface: pygame.Surface) -> None:
        title = theme.render("Storage is locked", 16, theme.WHITE, bold=True)
        surface.blit(title, title.get_rect(centerx=160, y=180))
        for i, line in enumerate((
            "Uploads can't be saved while the SD card",
            "is read-only. Unlock in Settings → Power,",
            "then reboot and try again.",
        )):
            s = theme.render(line, 11, theme.DIM)
            surface.blit(s, s.get_rect(centerx=160, y=220 + i * 18))
