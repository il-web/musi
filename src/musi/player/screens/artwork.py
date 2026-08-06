"""Artwork screen — fetch missing album art from the Cover Art Archive.

Manual only. The fetch is network- plus image-work at roughly one album per
second, so it runs on a worker thread and never starts on its own: on a Zero W
that would compete with playback for the single core.
"""
from __future__ import annotations

import threading

import pygame

from musi.library import art_fetch
from musi.player import audio_detect, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

FETCH_RECT = pygame.Rect(30, 300, 260, 64)

_INFO = (
    "Looks up albums with no cover by",
    "artist and title on MusicBrainz, then",
    "downloads the front cover.",
)


class ArtworkScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self.missing: int = 0
        self.running: bool = False
        self.done: tuple[int, int] | None = None
        self.progress: tuple[int, int, str] | None = None
        self.error: str = ""
        self._thread: threading.Thread | None = None
        self._hdr: pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        if self.running:
            return
        try:
            self.missing = len(
                art_fetch.albums_missing_art(self.app.db, self.app.art_dir))
        except Exception as exc:
            self.error = str(exc)
            self.missing = 0

    @property
    def animates(self) -> bool:
        return self.running

    def join(self, timeout: float = 10.0) -> None:
        """Wait for the worker — used by tests, and harmless in the app."""
        if self._thread is not None:
            self._thread.join(timeout)

    # ── state text ────────────────────────────────────────────────────────────

    def summary(self) -> str:
        if self.error:
            return f"Failed: {self.error}"
        if self.running:
            if self.progress is None:
                return "Starting…"
            done, total, label = self.progress
            return f"{done}/{total} · {label}"
        if self.done is not None:
            found, total = self.done
            return f"Found artwork for {found} of {total}"
        if self.missing == 0:
            return "All albums have artwork"
        word = "album" if self.missing == 1 else "albums"
        return f"{self.missing} {word} missing artwork"

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr = theme.render("Artwork", 16, theme.WHITE, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._hdr, (14, 26))

        s = theme.render(self.summary(), 13,
                         theme.DIM if self.error else theme.ACCENT, max_width=292)
        surface.blit(s, (14, 62))

        for i, line in enumerate(_INFO):
            t = theme.render(line, 11, theme.DIM, max_width=292)
            surface.blit(t, (14, 110 + i * 18))

        if self.running and self.progress is not None:
            done, total, _ = self.progress
            frac = (done / total) if total else 0.0
            bar = pygame.Rect(30, 250, 260, 10)
            pygame.draw.rect(surface, theme.CARD_BG, bar, border_radius=5)
            if frac > 0:
                fill = pygame.Rect(bar.x, bar.y, int(bar.w * frac), bar.h)
                pygame.draw.rect(surface, theme.ACCENT, fill, border_radius=5)

        enabled = not self.running and self.missing > 0
        label = "Fetching…" if self.running else "Fetch artwork"
        pygame.draw.rect(surface, theme.ACCENT if enabled else theme.CARD_BG,
                         FETCH_RECT, border_radius=12)
        ls = theme.render(label, 16, theme.WHITE if enabled else theme.DIM,
                          bold=True)
        surface.blit(ls, ls.get_rect(center=FETCH_RECT.center))

        minibar.draw(surface, self.app, status)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return None

        if FETCH_RECT.collidepoint(x, y):
            self._start()
            return None
        return super().handle_touch(x, y)

    # ── worker ────────────────────────────────────────────────────────────────

    def _start(self) -> None:
        if self.running or self.missing == 0:
            return
        self.running  = True
        self.error    = ""
        self.done     = None
        self.progress = None

        def work() -> None:
            try:
                self.done = art_fetch.fetch_missing(
                    self.app.db, self.app.art_dir,
                    progress=lambda d, t, label: setattr(
                        self, "progress", (d, t, label)),
                    should_stop=lambda: False,
                )
            except Exception as exc:
                self.error = str(exc)
            finally:
                self.running = False
                self.on_enter()          # recount what is still missing

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
