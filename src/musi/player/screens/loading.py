"""Loading screen — the second half of the boot look.

The Plymouth splash shows the "sound rings" (player/boot_look.py) from power
on, with "Starting services…" and the first part of the progress bar. This
screen is the same picture, continued: the bar picks up at boot_look's
APP_START and the status line moves on.

Steps (with real progress):
  1. Connecting to music (MPD)   40 % →  50 %
  2. Loading library (scan)      50 % →  92 %
  3. MPD database update         92 % →  98 %
  4. Ready                      100 %  → Home
"""
from __future__ import annotations

import threading
import time

import pygame

from musi.player import boot_look
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

_MIN_SHOW_S = 1.5   # always show the screen at least this long


class LoadingScreen(Screen):
    animates = True   # eq bars + progress — full FPS, no sleep

    def __init__(self, app) -> None:
        super().__init__(app)
        self._progress:  float = boot_look.APP_START   # 0.0 → 1.0, shared bar
        self._message:   "tuple[str, str] | str" = boot_look.CONNECTING
        self._done:      bool  = False
        self._started:   bool  = False
        self._start_t:   float = time.monotonic()

        self._start_draw: float = time.monotonic()   # for animation clock

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._progress = boot_look.APP_START
        self._message  = boot_look.CONNECTING
        self._done     = False
        self._started  = False
        self._start_t  = time.monotonic()

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        # Kick off the background work on the very first draw (pygame is ready)
        if not self._started:
            self._started = True
            threading.Thread(target=self._work, daemon=True).start()

        # Transition once done AND minimum display time has passed
        if self._done and (time.monotonic() - self._start_t) >= _MIN_SHOW_S:
            self._go_home()
            return

        boot_look.draw(surface, time.monotonic() - self._start_draw,
                       self._message, self._progress)

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
            self._progress = 1.0
        except Exception as exc:
            self._message  = f"Error: {exc}"
            self._progress = 1.0
            time.sleep(2.0)
        finally:
            self._done = True

    # ── step 1 — MPD connection (40 % → 50 %) ────────────────────────────────

    def _step1_connect(self) -> None:
        self._message  = boot_look.CONNECTING
        self._progress = boot_look.APP_START

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if self.app.status.connected:
                break
            # Try an explicit reconnect
            try:
                self.app.mpd.connect()
            except Exception:
                import logging
                logging.warning('Ignored exception', exc_info=True)
            time.sleep(0.4)
            self._progress = min(0.49, self._progress + 0.01)

        self._progress = 0.50

    # ── step 2 — library scan (50 % → 92 %) ──────────────────────────────────

    def _step2_scan(self) -> None:
        self._message = boot_look.LOADING
        self._progress = 0.50

        from musi.library.config import art_dir, db_path, music_root
        from musi.library.db import open_db
        from musi.library.scanner import scan

        # Use a separate DB connection so the main thread's connection is free
        scan_conn = open_db(db_path())

        def on_progress(current: int, total: int, filename: str) -> None:
            if total > 0:
                self._progress = 0.50 + (current / total) * 0.42
            else:
                self._progress = 0.92

        try:
            stats = scan(
                music_root=music_root(),
                art_dir=art_dir(),
                conn=scan_conn,
                progress=on_progress,
            )
        finally:
            scan_conn.close()

        if stats["added"] or stats["updated"]:
            import logging
            logging.info("library: +%d new, %d updated", stats["added"], stats["updated"])
        self._progress = 0.92

    # ── step 3 — MPD db update (92 % → 98 %) ─────────────────────────────────

    def _step3_mpd_update(self) -> None:
        self._progress = 0.94
        self._apply_prefs()
        self.app.mpd.db_update()
        self._progress = 0.98

    def _apply_prefs(self) -> None:
        """Push stored playback preferences into MPD.

        MPD keeps crossfade and ReplayGain in its own state file, so a preference changed
        while the daemon was down would otherwise disagree with what the
        Playback screen shows. Best-effort: a failure here must not stop boot.
        """
        from musi.player import prefs
        from musi.player.screens.playback import CROSSFADE_S
        try:
            on = bool(prefs.get("crossfade"))
            self.app.mpd.set_crossfade(CROSSFADE_S if on else 0)
            self.app.mpd.set_replay_gain(bool(prefs.get("replaygain")))
        except Exception:
            import logging
            logging.warning("could not apply playback prefs", exc_info=True)

    # ── transition ────────────────────────────────────────────────────────────

    def _go_home(self) -> None:
        from musi.player.screens.launcher import LauncherScreen
        self.app._stack.clear()
        launcher = LauncherScreen(self.app)
        self.app._stack.append(launcher)
        launcher.on_enter()
        # "system update needed" / "restart to finish" — once, on top of Home
        from musi.player.screens.system_update import maybe_show
        maybe_show(self.app)
