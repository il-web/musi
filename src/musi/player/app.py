"""Main application — pygame window, event loop, and screen stack."""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pygame

from musi.player import backlight, theme
from musi.player.input import Button, key_to_button
from musi.player.mpd_client import MusiMPDClient, PlayerStatus
from musi.player.screen import Screen

# ── constants ─────────────────────────────────────────────────────────────────
DISPLAY_W, DISPLAY_H = 320, 480   # matches ST7796 — draw at this resolution
WINDOW_W,  WINDOW_H  = 640, 960   # desktop window size (2× scale via GPU)
ACTIVE_FPS      = 30              # while interacting / animating
IDLE_FPS        = 10              # static screen — big CPU + SPI saver on the Zero W
OFF_FPS         = 5               # screen off — just watch for the wake tap
ACTIVE_WINDOW_S = 1.5             # stay at full FPS this long after the last input
POLL_INTERVAL   = 1.0             # seconds between MPD status polls
TAP_SLOP_PX     = 12              # movement below this still counts as a tap
LONG_PRESS_S    = 0.5             # hold this long without moving → long-press

# Screen dims after MUSI_DIM_S and blanks (backlight off) after MUSI_OFF_S
# seconds without touch/key input; 0 disables that stage. Any tap wakes it.
DIM_AFTER_S = float(os.environ.get("MUSI_DIM_S", "30"))
OFF_AFTER_S = float(os.environ.get("MUSI_OFF_S", "90"))

_INPUT_EVENTS = (
    pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
    pygame.MOUSEMOTION, pygame.MOUSEWHEEL,
    pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP,
)
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
        self._poll_time:       float        = 0.0   # when _status was fetched
        self._running:         bool         = False
        self._last_track_path: str | None   = None
        self._sleep_at:        float | None = None   # sleep timer deadline (ticks s)

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

    def request_poll(self) -> None:
        """Force an MPD status refresh on the next frame.

        Call after any command that changes player state so the UI reflects
        it within one frame instead of waiting out POLL_INTERVAL.
        """
        self._last_poll = 0.0

    def toggle_play(self) -> None:
        """Play/pause with an optimistic local state flip for instant feedback."""
        self._mpd.play_pause()
        if self._status.connected:
            new_state = "pause" if self._status.state == "play" else "play"
            self._status = replace(self._status, state=new_state)
        self.request_poll()

    def set_sleep_timer(self, minutes: float | None) -> None:
        """Pause playback after `minutes`; None cancels the timer."""
        if minutes is None:
            self._sleep_at = None
        else:
            self._sleep_at = pygame.time.get_ticks() / 1000.0 + minutes * 60

    def sleep_remaining(self) -> float | None:
        """Seconds until the sleep timer fires, or None if not set."""
        if self._sleep_at is None:
            return None
        return max(0.0, self._sleep_at - pygame.time.get_ticks() / 1000.0)

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
            self._bt_active = False
            return
        self._bt_active = True

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

        # touch-drag state — tells taps, scroll swipes, drags and long-presses apart
        self._touch_start:  tuple[int, int] | None = None
        self._touch_t:      float = 0.0    # when the gesture began
        self._touch_moved:  float = 0.0
        self._captured:     bool  = False  # a screen grabbed this gesture as a drag
        self._long_checked: bool  = False  # long-press already evaluated
        self._long_fired:   bool  = False  # long-press handled → swallow the tap

        # screen power state (dim → backlight off after inactivity)
        self._last_input: float = pygame.time.get_ticks() / 1000.0
        self._screen_off: bool  = False
        self._wake_flip:  bool  = False    # backlight on after next flip (fresh frame)
        self._bt_active:  bool  = False    # BT-switch overlay currently showing
        self._dim_surf:   pygame.Surface | None = None
        backlight.set_on(True)             # recover if a previous run left it dark

        self.push(initial_screen)
        self._running = True

        while self._running:
            now = pygame.time.get_ticks() / 1000.0

            # ── poll MPD ──────────────────────────────────────────────────────
            if now - self._last_poll >= POLL_INTERVAL:
                self._status    = self._mpd.poll()
                self._last_poll = now
                self._poll_time = now
                self._maybe_record_play()

            # ── sleep timer ───────────────────────────────────────────────────
            if self._sleep_at is not None and now >= self._sleep_at:
                self._sleep_at = None
                if self._status.state == "play":
                    self._mpd.pause()
                    self.request_poll()

            # ── events ────────────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    continue
                if event.type in _INPUT_EVENTS:
                    self._last_input = now
                    if self._screen_off or self._wake_flip:
                        # first input after screen-off only wakes the panel —
                        # swallow it so the wake tap doesn't press anything
                        self._screen_off = False
                        self._wake_flip  = True
                        continue
                if event.type == pygame.KEYDOWN:
                    consumed = (
                        self._stack[-1].handle_event(event) if self._stack else False
                    )
                    if not consumed:
                        btn = key_to_button(event.key)
                        if btn and self._stack:
                            self._stack[-1].handle(btn, self._status)
                # Touch and mouse share one gesture flow: press → move → release.
                # KMSDRM delivers touches as finger events; the desktop window
                # sends mouse events. A screen may grab the gesture as a drag
                # (volume/seek slider, queue reorder) via on_press; otherwise
                # motion scrolls, a still hold long-presses, a short tap taps.
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._begin_touch(*event.pos, now)
                elif event.type == pygame.MOUSEMOTION:
                    if event.buttons[0]:
                        self._move_touch(*event.pos, event.rel[0], event.rel[1])
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self._end_touch(*event.pos)
                elif event.type == pygame.FINGERDOWN:
                    self._begin_touch(int(event.x * DISPLAY_W),
                                      int(event.y * DISPLAY_H), now)
                elif event.type == pygame.FINGERMOTION:
                    self._move_touch(int(event.x * DISPLAY_W),
                                     int(event.y * DISPLAY_H),
                                     event.dx * DISPLAY_W, event.dy * DISPLAY_H)
                elif event.type == pygame.FINGERUP:
                    self._end_touch(int(event.x * DISPLAY_W),
                                    int(event.y * DISPLAY_H))
                elif event.type == pygame.MOUSEWHEEL:
                    if self._stack:
                        self._stack[-1].handle_scroll(event.y * 40)

            # ── long-press: finger held still, gesture not captured ────────────
            if (self._touch_start is not None and not self._captured
                    and not self._long_checked
                    and self._touch_moved < TAP_SLOP_PX
                    and now - self._touch_t >= LONG_PRESS_S):
                self._long_checked = True
                if self._stack:
                    self._long_fired = bool(
                        self._stack[-1].handle_long_press(*self._touch_start)
                    )

            # ── screen power (dim → off after inactivity) ─────────────────────
            top = self._stack[-1] if self._stack else None
            top_animates = bool(top and top.animates)
            if top_animates:
                # animated screens (loading, transfers, updates) never sleep
                self._last_input = now
            idle = now - self._last_input

            # screens may override the timeouts (e.g. Now Playing stays on)
            dim_after = top.dim_after if top and top.dim_after is not None else DIM_AFTER_S
            off_after = top.off_after if top and top.off_after is not None else OFF_AFTER_S

            if off_after > 0 and idle >= off_after and not self._screen_off:
                self._screen_off = True
                surface.fill((0, 0, 0))
                pygame.display.flip()      # blank the panel even without backlight ctl
                backlight.set_on(False)

            if self._screen_off:
                # no drawing, no SPI traffic — just keep watching for the wake tap
                clock.tick(OFF_FPS)
                continue

            # ── draw ──────────────────────────────────────────────────────────
            # Extrapolate elapsed between polls so progress moves every frame
            # instead of jumping once per POLL_INTERVAL.
            draw_status = self._status
            if draw_status.state == "play" and draw_status.duration > 0:
                draw_status = replace(
                    draw_status,
                    elapsed=min(
                        draw_status.duration,
                        draw_status.elapsed + (now - self._poll_time),
                    ),
                )

            surface.fill((10, 10, 15))
            if self._stack:
                self._stack[-1].draw(surface, draw_status)

            self._draw_bt_overlay(surface)

            # dim stage — darken the finished frame
            if dim_after > 0 and idle >= dim_after:
                if self._dim_surf is None:
                    self._dim_surf = pygame.Surface((DISPLAY_W, DISPLAY_H), pygame.SRCALPHA)
                    self._dim_surf.fill((0, 0, 0, 150))
                surface.blit(self._dim_surf, (0, 0))

            pygame.display.flip()

            if self._wake_flip:
                # a fresh frame is on the panel — now light it up (no stale flash)
                self._wake_flip = False
                backlight.set_on(True)

            # ── adaptive frame rate ───────────────────────────────────────────
            interacting = (
                idle < ACTIVE_WINDOW_S
                or self._captured
                or self._touch_start is not None
            )
            clock.tick(
                ACTIVE_FPS if (interacting or top_animates or self._bt_active)
                else IDLE_FPS
            )

        backlight.set_on(True)             # don't strand the panel dark on exit
        self._mpd.disconnect()
        pygame.quit()

    # ── unified touch/mouse gesture flow ──────────────────────────────────────

    def _begin_touch(self, x: int, y: int, now: float) -> None:
        if not self._stack:
            return
        scr = self._stack[-1]
        self._touch_start  = (x, y)
        self._touch_t      = now
        self._touch_moved  = 0.0
        self._long_checked = False
        self._long_fired   = False
        self._captured     = bool(scr.on_press(x, y))
        if not self._captured:
            scr.handle_scroll_start()

    def _move_touch(self, x: int, y: int, dx: float, dy: float) -> None:
        if self._touch_start is None or not self._stack:
            return
        self._touch_moved += abs(dx) + abs(dy)
        if self._captured:
            self._stack[-1].on_drag(x, y)
        else:
            self._stack[-1].handle_scroll(dy)

    def _end_touch(self, x: int, y: int) -> None:
        if self._touch_start is not None and self._stack:
            scr = self._stack[-1]
            if self._captured:
                scr.on_release(x, y)
            else:
                scr.handle_scroll_end()
                if self._touch_moved < TAP_SLOP_PX and not self._long_fired:
                    btn = scr.handle_touch(*self._touch_start)
                    if btn is not None:
                        scr.handle(btn, self._status)
        self._touch_start = None
        self._captured    = False

    # ── internal ──────────────────────────────────────────────────────────────

    def _maybe_record_play(self) -> None:
        path = self._status.path
        if self._status.state == "play" and path and path != self._last_track_path:
            self._mpd.record_play(self._db, path)
            self._last_track_path = path
