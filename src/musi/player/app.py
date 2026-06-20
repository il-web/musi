"""Main application — pygame window, event loop, and screen stack."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pygame

from musi.player import theme
from musi.player.input import Button, key_to_button
from musi.player.mpd_client import MusiMPDClient, PlayerStatus
from musi.player.screen import Screen

# ── constants ─────────────────────────────────────────────────────────────────
DISPLAY_W, DISPLAY_H = 320, 480   # matches ST7796 — draw at this resolution
WINDOW_W,  WINDOW_H  = 640, 960   # desktop window size (2× scale via GPU)
FPS           = 30
POLL_INTERVAL = 1.0               # seconds between MPD status polls
# Flag file written by the musi-bt-router service while it switches BT output
# (contains the target device name); removed once MPD is back up.
BT_CONNECTING_FLAG = "/tmp/musi-bt-connecting"


class App:
    def __init__(
        self,
        mpd: MusiMPDClient,
        db:  sqlite3.Connection,
        art_dir: Path,
    ) -> None:
        self._mpd     = mpd
        self._db      = db
        self._art_dir = art_dir

        self._stack:           list[Screen] = []
        self._status:          PlayerStatus = PlayerStatus.disconnected()
        self._last_poll:       float        = 0.0
        self._running:         bool         = False
        self._last_track_path: str | None   = None

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def stack(self)   -> list[Screen]:        return self._stack
    @property
    def mpd(self)     -> MusiMPDClient:       return self._mpd
    @property
    def db(self)      -> sqlite3.Connection:  return self._db
    @property
    def art_dir(self) -> Path:                return self._art_dir
    @property
    def status(self)  -> PlayerStatus:        return self._status

    def push(self, screen: Screen) -> None:
        if self._stack:
            self._stack[-1].on_exit()
        self._stack.append(screen)
        screen.on_enter()

    def pop(self) -> None:
        if len(self._stack) > 1:
            self._stack[-1].on_exit()
            self._stack.pop()
            self._stack[-1].on_enter()

    def quit(self) -> None:
        self._running = False

    # ── bluetooth switch overlay ────────────────────────────────────────────────

    def _draw_bt_overlay(self, surface: "pygame.Surface") -> None:
        """While the BT auto-router switches output, show a 'Connecting to …' card.

        The musi-bt-router service writes the device name to BT_CONNECTING_FLAG
        when a switch begins and removes it once MPD is back, so this appears and
        disappears on its own.
        """
        try:
            name = open(BT_CONNECTING_FLAG).read().strip()
        except OSError:
            return

        dim = pygame.Surface((DISPLAY_W, DISPLAY_H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        surface.blit(dim, (0, 0))

        box = pygame.Rect(0, 0, 280, 112)
        box.center = (DISPLAY_W // 2, DISPLAY_H // 2)
        pygame.draw.rect(surface, theme.CARD_BG, box, border_radius=14)

        dots  = "." * (1 + (pygame.time.get_ticks() // 400) % 3)
        title = theme.render("Connecting to", 12, theme.DIM)
        nm    = theme.render(name or "Bluetooth device", 17, theme.WHITE, bold=True, max_width=250)
        sub   = theme.render(dots, 18, theme.ACCENT)
        surface.blit(title, title.get_rect(centerx=DISPLAY_W // 2, y=box.y + 22))
        surface.blit(nm,    nm.get_rect(centerx=DISPLAY_W // 2, y=box.y + 44))
        surface.blit(sub,   sub.get_rect(centerx=DISPLAY_W // 2, y=box.y + 80))

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self, initial_screen: Screen) -> None:
        pygame.init()
        pygame.display.set_caption("musi")

        if sys.platform == "linux" and not os.environ.get("DISPLAY"):
            pygame.display.set_mode(
                (DISPLAY_W, DISPLAY_H),
                pygame.FULLSCREEN | pygame.SCALED,
            )
        else:
            pygame.display.set_mode(
                (DISPLAY_W, DISPLAY_H),
                pygame.SCALED | pygame.RESIZABLE,
            )

        surface = pygame.display.get_surface()
        clock   = pygame.time.Clock()

        # touch-drag state — lets us tell a tap from a scroll swipe / drag gesture
        self._touch_start: tuple[int, int] | None = None
        self._touch_moved: float = 0.0
        self._captured:    bool  = False   # a screen grabbed this gesture as a drag

        self.push(initial_screen)
        self._running = True

        while self._running:
            now = pygame.time.get_ticks() / 1000.0

            # ── poll MPD ──────────────────────────────────────────────────────
            if now - self._last_poll >= POLL_INTERVAL:
                self._status    = self._mpd.poll()
                self._last_poll = now
                self._maybe_record_play()

            # ── events ────────────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                elif event.type == pygame.KEYDOWN:
                    consumed = (
                        self._stack[-1].handle_event(event) if self._stack else False
                    )
                    if not consumed:
                        btn = key_to_button(event.key)
                        if btn and self._stack:
                            self._stack[-1].handle(btn, self._status)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self._stack:
                        scr = self._stack[-1]
                        self._captured = scr.on_press(*event.pos)
                        if not self._captured:
                            btn = scr.handle_touch(*event.pos)
                            if btn is not None:
                                scr.handle(btn, self._status)
                elif event.type == pygame.MOUSEMOTION:
                    if self._captured and event.buttons[0] and self._stack:
                        self._stack[-1].on_drag(*event.pos)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if self._captured and self._stack:
                        self._stack[-1].on_release(*event.pos)
                    self._captured = False
                elif event.type == pygame.FINGERDOWN:
                    # KMSDRM delivers touches as finger events. A screen may grab the
                    # gesture as a drag (volume slider / queue reorder) via on_press;
                    # otherwise motion scrolls and a small move counts as a tap.
                    x = int(event.x * DISPLAY_W); y = int(event.y * DISPLAY_H)
                    self._touch_start = (x, y)
                    self._touch_moved = 0.0
                    self._captured = bool(self._stack and self._stack[-1].on_press(x, y))
                elif event.type == pygame.FINGERMOTION:
                    if self._touch_start is not None and self._stack:
                        x = int(event.x * DISPLAY_W); y = int(event.y * DISPLAY_H)
                        dy = event.dy * DISPLAY_H
                        self._touch_moved += abs(event.dx * DISPLAY_W) + abs(dy)
                        if self._captured:
                            self._stack[-1].on_drag(x, y)
                        else:
                            self._stack[-1].handle_scroll(dy)
                elif event.type == pygame.FINGERUP:
                    if self._touch_start is not None and self._stack:
                        x = int(event.x * DISPLAY_W); y = int(event.y * DISPLAY_H)
                        if self._captured:
                            self._stack[-1].on_release(x, y)
                        elif self._touch_moved < 12:    # barely moved → a tap
                            scr = self._stack[-1]
                            btn = scr.handle_touch(*self._touch_start)
                            if btn is not None:
                                scr.handle(btn, self._status)
                    self._touch_start = None
                    self._captured = False
                elif event.type == pygame.MOUSEWHEEL:
                    if self._stack:
                        self._stack[-1].handle_scroll(event.y * 40)

            # ── draw ──────────────────────────────────────────────────────────
            surface.fill((10, 10, 15))
            if self._stack:
                self._stack[-1].draw(surface, self._status)

            self._draw_bt_overlay(surface)

            pygame.display.flip()
            clock.tick(FPS)

        self._mpd.disconnect()
        pygame.quit()

    # ── internal ──────────────────────────────────────────────────────────────

    def _maybe_record_play(self) -> None:
        path = self._status.path
        if self._status.state == "play" and path and path != self._last_track_path:
            self._mpd.record_play(self._db, path)
            self._last_track_path = path
