"""Shared touch widgets — kinetic list scrolling, deferred tap flash, scrollbar.

KineticList is a pixel-based scroll model with momentum for uniform-row lists:
screens feed it finger deltas plus start/end signals, call update() once per
frame, and read first_visible()/pixel_shift() for drawing and index_at() for
hit-testing.

PendingTap defers a tap action for a moment so the pressed row is visibly
highlighted before the action runs (pressed-state flash).
"""
from __future__ import annotations

import time
from collections import deque

import pygame

from musi.player import theme


class KineticList:
    DECAY      = 0.04   # fraction of velocity left after 1 s of coasting
    MIN_VEL    = 8.0    # px/s — stop coasting below this
    SAMPLE_WIN = 0.10   # seconds of recent finger movement used for fling speed

    def __init__(self, item_h: int, view_h: int) -> None:
        self.item_h = item_h
        self.view_h = view_h
        self.count  = 0
        self.offset = 0.0                 # px from list top, 0..max_offset
        self._vel   = 0.0                 # px/s while coasting
        self._samples: deque = deque()    # (t, dy) recent finger moves
        self._touching = False
        self._last_t   = time.monotonic()

    @property
    def max_offset(self) -> float:
        return max(0.0, self.count * self.item_h - self.view_h)

    def set_count(self, n: int, reset: bool = False) -> None:
        self.count = n
        if reset:
            self.offset = 0.0
        self._vel  = 0.0
        self.offset = min(self.offset, self.max_offset)

    # ── gesture input ──────────────────────────────────────────────────────────

    def start_touch(self) -> None:
        """Finger down — catching the list stops any coast."""
        self._touching = True
        self._vel = 0.0
        self._samples.clear()

    def scroll_by(self, dy: float) -> None:
        """Finger moved dy px (positive = downward); content follows finger."""
        self.offset = max(0.0, min(self.max_offset, self.offset - dy))
        now = time.monotonic()
        self._samples.append((now, dy))
        while self._samples and now - self._samples[0][0] > self.SAMPLE_WIN:
            self._samples.popleft()

    def end_touch(self) -> None:
        """Finger up — convert recent movement into coasting velocity."""
        self._touching = False
        now = time.monotonic()
        moves = [(t, dy) for t, dy in self._samples if now - t <= self.SAMPLE_WIN]
        if len(moves) >= 2:
            dt = now - moves[0][0]
            if dt > 0.001:
                self._vel = -sum(dy for _, dy in moves) / dt
        self._samples.clear()

    # ── per-frame ──────────────────────────────────────────────────────────────

    def update(self) -> bool:
        """Advance coasting. Returns True while the list is still moving."""
        now = time.monotonic()
        dt  = min(0.1, now - self._last_t)
        self._last_t = now
        if self._touching or abs(self._vel) < self.MIN_VEL:
            self._vel = 0.0
            return False
        self.offset += self._vel * dt
        if self.offset <= 0.0 or self.offset >= self.max_offset:
            self.offset = max(0.0, min(self.max_offset, self.offset))
            self._vel = 0.0
            return False
        self._vel *= self.DECAY ** dt
        return True

    # ── geometry ───────────────────────────────────────────────────────────────

    def first_visible(self) -> int:
        return int(self.offset // self.item_h)

    def pixel_shift(self) -> int:
        return int(self.offset - self.first_visible() * self.item_h)

    def visible_rows(self) -> int:
        return self.view_h // self.item_h + 2   # partial rows top + bottom

    def index_at(self, y_view: float) -> int:
        """Item index for a y relative to the list's top edge."""
        return int((y_view + self.offset) // self.item_h)

    def jump_to(self, idx: int) -> None:
        """Snap row idx to the top of the view (no animation)."""
        self.offset = max(0.0, min(self.max_offset, float(idx * self.item_h)))
        self._vel = 0.0

    def ensure_visible(self, idx: int) -> None:
        """Scroll the minimum amount so row idx is fully on screen."""
        top = idx * self.item_h
        if top < self.offset:
            self.offset = float(top)
        elif top + self.item_h > self.offset + self.view_h:
            self.offset = float(top + self.item_h - self.view_h)
        self._vel = 0.0


class PendingTap:
    """Defers a tap action briefly so the pressed row is visibly highlighted."""

    DELAY = 0.12   # seconds the highlight shows before the action runs

    def __init__(self) -> None:
        self._action = None
        self._t = 0.0

    @property
    def pending(self) -> bool:
        return self._action is not None

    def set(self, action) -> None:
        """Arm the flash; ignored if another tap is already pending."""
        if self._action is None:
            self._action = action
            self._t = time.monotonic()

    def update(self) -> None:
        """Call once per frame; runs the action once the flash has shown."""
        if self._action and time.monotonic() - self._t >= self.DELAY:
            action, self._action = self._action, None
            action()


def draw_scrollbar(surface: pygame.Surface, x: int, y: int, h: int,
                   klist: KineticList) -> None:
    """Thin right-edge scrollbar driven by a KineticList's pixel offset."""
    if klist.max_offset <= 0:
        return
    pygame.draw.rect(surface, (30, 30, 44), (x, y, 2, h), border_radius=1)
    frac    = klist.view_h / max(1, klist.count * klist.item_h)
    thumb_h = max(16, int(h * frac))
    thumb_y = y + int((h - thumb_h) * klist.offset / klist.max_offset)
    pygame.draw.rect(surface, theme.DIM, (x, thumb_y, 2, thumb_h), border_radius=1)
