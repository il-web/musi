"""Loading / splash screen — real startup sequence with progress bar.

Steps (with real progress):
  1. Connecting to MPD            0 % →  15 %
  2. Scanning music library      15 % →  85 %
  3. Updating MPD database       85 % →  95 %
  4. Ready                       95 % → 100 %  → transition to Home
"""
from __future__ import annotations

import math
import threading
import time

import pygame

from musi.player import theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

_MIN_SHOW_S = 1.5   # always show the screen at least this long


class LoadingScreen(Screen):
    animates = True   # eq bars + progress — full FPS, no sleep

    def __init__(self, app) -> None:
        super().__init__(app)
        self._progress:  float = 0.0     # 0.0 → 1.0
        self._message:   str   = "Starting…"
        self._detail:    str   = ""      # e.g. current filename
        self._done:      bool  = False
        self._started:   bool  = False
        self._start_t:   float = time.monotonic()

        # static surfaces (built lazily after pygame.init)
        self._logo_surf:  pygame.Surface | None = None
        self._start_draw: float = time.monotonic()   # for animation clock

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._progress = 0.0
        self._message  = "Starting…"
        self._detail   = ""
        self._done     = False
        self._started  = False
        self._start_t  = time.monotonic()

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._logo_surf is None:
            self._logo_surf = theme.render("musi", 44, theme.WHITE, bold=True)

        # Kick off the background work on the very first draw (pygame is ready)
        if not self._started:
            self._started = True
            threading.Thread(target=self._work, daemon=True).start()

        # Transition once done AND minimum display time has passed
        if self._done and (time.monotonic() - self._start_t) >= _MIN_SHOW_S:
            self._go_home()
            return

        # ── background ────────────────────────────────────────────────────────
        surface.fill(theme.BG)
        cx  = 160
        now = time.monotonic() - self._start_draw

        # ── logo (slight pulse — scale opacity 220→255) ───────────────────────
        alpha  = int(220 + 35 * (0.5 + 0.5 * math.sin(now * 1.8)))
        logo_c = tuple(int(c * alpha / 255) for c in theme.WHITE)
        logo_s = theme.render("musi", 48, logo_c, bold=True)
        surface.blit(logo_s, logo_s.get_rect(centerx=cx, centery=126))

        # ── equalizer bars ────────────────────────────────────────────────────
        _draw_eq(surface, cx, 190, now, theme.ACCENT)

        # ── progress bar ──────────────────────────────────────────────────────
        bx, by, bw, bh = 28, 224, 264, 8
        pygame.draw.rect(surface, (30, 30, 46), (bx, by, bw, bh), border_radius=4)
        filled = max(bh, int(bw * self._progress))
        pygame.draw.rect(surface, theme.ACCENT, (bx, by, filled, bh), border_radius=4)

        # percentage label to the right of the bar
        pct_s = theme.render(f"{int(self._progress * 100)}%", 10, theme.DIM)
        surface.blit(pct_s, (bx + bw + 6, by))

        # ── step message ──────────────────────────────────────────────────────
        msg_s = theme.render(self._message, 12, theme.WHITE, max_width=280)
        surface.blit(msg_s, msg_s.get_rect(centerx=cx, y=246))

        # ── file detail (small, dim) ──────────────────────────────────────────
        if self._detail:
            det_s = theme.render(self._detail, 10, theme.DIM, max_width=280)
            surface.blit(det_s, det_s.get_rect(centerx=cx, y=264))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        pass   # no skipping — let the scan finish

    # ── background work ───────────────────────────────────────────────────────

    def _work(self) -> None:
        """Run the full startup sequence in a daemon thread."""
        try:
            self._step1_connect()
            self._step2_scan()
            self._step3_mpd_update()
            self._message  = "Ready!"
            self._detail   = ""
            self._progress = 1.0
        except Exception as exc:
            self._message  = f"Error: {exc}"
            self._progress = 1.0
            time.sleep(2.0)
        finally:
            self._done = True

    # ── step 1 — MPD connection (0 % → 15 %) ─────────────────────────────────

    def _step1_connect(self) -> None:
        self._message  = "Connecting to MPD…"
        self._progress = 0.03

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if self.app.status.connected:
                break
            # Try an explicit reconnect
            try:
                self.app.mpd.connect()
            except Exception:
                pass
            time.sleep(0.4)
            self._progress = min(0.14, self._progress + 0.02)

        self._progress = 0.15

    # ── step 2 — library scan (15 % → 85 %) ──────────────────────────────────

    def _step2_scan(self) -> None:
        self._message = "Scanning music library…"
        self._detail  = ""
        self._progress = 0.15

        from musi.library.config import art_dir, db_path, music_root
        from musi.library.db import open_db
        from musi.library.scanner import scan

        # Use a separate DB connection so the main thread's connection is free
        scan_conn = open_db(db_path())
        _total_files = [0]

        def on_progress(current: int, total: int, filename: str) -> None:
            _total_files[0] = total
            if total > 0:
                self._progress = 0.15 + (current / total) * 0.70
                self._message  = f"Scanning… {current} / {total}"
                self._detail   = filename
            else:
                self._progress = 0.85

        try:
            stats = scan(
                music_root=music_root(),
                art_dir=art_dir(),
                conn=scan_conn,
                progress=on_progress,
            )
        finally:
            scan_conn.close()

        self._detail = ""
        added   = stats["added"]
        updated = stats["updated"]

        if added or updated:
            self._message = f"+{added} new  ·  {updated} updated"
        elif _total_files[0] == 0:
            self._message = "Library up to date"
        else:
            self._message = f"{_total_files[0]} tracks — nothing changed"

        self._progress = 0.85
        time.sleep(0.6)   # let the user read the result

    # ── step 3 — MPD db update (85 % → 95 %) ─────────────────────────────────

    def _step3_mpd_update(self) -> None:
        self._message  = "Updating MPD database…"
        self._detail   = ""
        self._progress = 0.88
        self.app.mpd.db_update()
        time.sleep(0.4)
        self._progress = 0.95

    # ── transition ────────────────────────────────────────────────────────────

    def _go_home(self) -> None:
        from musi.player.screens.home import HomeScreen
        self.app._stack.clear()
        home = HomeScreen(self.app)
        self.app._stack.append(home)
        home.on_enter()


# ── equalizer animation ───────────────────────────────────────────────────────

# Per-bar: (oscillation frequency, phase offset)
_BAR_PARAMS = [
    (1.7, 0.0),
    (2.5, 0.9),
    (1.2, 1.8),
    (3.1, 0.4),
    (1.9, 2.5),
    (2.3, 1.2),
    (1.5, 3.0),
    (2.8, 0.6),
    (1.3, 2.1),
]

def _draw_eq(
    surface: pygame.Surface,
    cx: int,
    bottom_y: int,
    t: float,
    accent: tuple,
) -> None:
    """Draw animated equalizer bars centred at cx, anchored at bottom_y."""
    n      = len(_BAR_PARAMS)
    bar_w  = 7
    gap    = 4
    max_h  = 28
    min_h  = 4
    total_w = n * bar_w + (n - 1) * gap
    x0      = cx - total_w // 2

    for i, (freq, phase) in enumerate(_BAR_PARAMS):
        h = int(min_h + (max_h - min_h) * (0.5 + 0.5 * math.sin(t * freq + phase)))
        x = x0 + i * (bar_w + gap)
        y = bottom_y - h

        # Colour: blend from DIM (short) to ACCENT (tall)
        ratio = (h - min_h) / max(1, max_h - min_h)
        col   = tuple(int(d + (a - d) * ratio)
                      for d, a in zip((80, 80, 95), accent))

        pygame.draw.rect(surface, col, (x, y, bar_w, h), border_radius=2)
