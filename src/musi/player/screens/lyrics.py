"""Lyrics screen — synced words for the track that was playing when it opened.

Opened from the Now Playing lyrics button. The fetch happens once, on a worker
thread, for that one track; afterwards it is served from disk. The screen is
pinned to the track it was opened for, so a song change mid-read does not swap
the words out from under you — go back and reopen.

Synced lyrics auto-scroll with the current line centred and highlighted, and
tapping a line seeks there. Plain lyrics are shown scrollable with no highlight.
"""
from __future__ import annotations

import threading

import pygame

from musi.library import lyrics as lyrics_lib
from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

TOP        = 34                 # first pixel below the status bar we draw into
BOTTOM     = 480
LINE_H     = 30                 # synced line pitch
PLAIN_H    = 22                 # plain line pitch
FOCUS_Y    = 230                # the active line sits here
RETRY_RECT = pygame.Rect(90, 300, 140, 48)

_MAX_W = 292


def _wrap(text: str, size: int, bold: bool, max_w: int,
          max_rows: int = 2) -> list[str]:
    """Word-wrap into at most max_rows rows; the last row may still truncate."""
    font = theme.font(size, bold)
    if font.size(text)[0] <= max_w:
        return [text]
    rows: list[str] = []
    words = text.split()
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and font.size(trial)[0] > max_w:
            rows.append(cur)
            cur = word
            if len(rows) == max_rows - 1:
                break
        else:
            cur = trial
    remaining = words[sum(len(r.split()) for r in rows):]
    rows.append(" ".join(remaining) if remaining else cur)
    return rows[:max_rows]


class LyricsScreen(Screen):

    def __init__(self, app, status: PlayerStatus) -> None:
        super().__init__(app)
        # pinned copies — the live status keeps moving, this screen must not
        self.artist   = getattr(status, "artist", "") or ""
        self.title    = getattr(status, "title", "") or ""
        self.album    = getattr(status, "album", "") or ""
        self.duration = float(getattr(status, "duration", 0.0) or 0.0)
        self.path     = getattr(status, "path", "") or ""

        self.loading = False
        self.result: lyrics_lib.Lyrics | None = None
        self.scroll  = 0.0            # plain-lyrics finger scroll
        self._thread: threading.Thread | None = None
        self._surfs: dict[int, pygame.Surface] = {}
        self._hdr: pygame.Surface | None = None
        self._laid: list[tuple[int, int]] = []   # (index, y) drawn last frame

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        if self.result is None and not self.loading:
            self._start(force=False)

    @property
    def animates(self) -> bool:
        return self.loading

    def join(self, timeout: float = 10.0) -> None:
        """Wait for the worker — used by tests, harmless in the app."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _start(self, *, force: bool) -> None:
        if self.loading:
            return
        self.loading = True
        self._surfs.clear()

        def work() -> None:
            try:
                self.result = lyrics_lib.get_lyrics(
                    self.app.lyrics_dir, self.artist, self.title,
                    self.album, self.duration, force=force)
            except Exception as exc:
                self.result = lyrics_lib.Lyrics(error=str(exc))
            finally:
                self.loading = False

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    # ── state ─────────────────────────────────────────────────────────────────

    def message(self) -> str:
        """Why there is nothing to show."""
        r = self.result
        if r is None:
            return "Loading…"
        if r.error:
            return f"Couldn't load lyrics: {r.error}"
        if r.instrumental:
            return "This track is instrumental"
        if not r.found:
            return "No lyrics found for this track"
        return ""

    def active_at(self, status: PlayerStatus) -> int:
        r = self.result
        if r is None or not r.synced:
            return -1
        return lyrics_lib.active_index(
            r.lines, float(getattr(status, "elapsed", 0.0) or 0.0))

    def line_y(self, index: int) -> int | None:
        """Screen y of a synced line as last drawn, or None if off-screen."""
        for i, y in self._laid:
            if i == index:
                return y
        return None

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr = theme.render(self.title or "Lyrics", 13, theme.WHITE,
                                     bold=True, max_width=_MAX_W)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._hdr, self._hdr.get_rect(centerx=160, y=TOP))

        self._laid = []
        r = self.result

        if self.loading:
            self._centre_text(surface, "Loading lyrics…", theme.DIM)
            return

        if r is not None and r.synced:
            self._draw_synced(surface, r, self.active_at(status))
        elif r is not None and r.found:
            self._draw_plain(surface, r)
        else:
            self._centre_text(surface, self.message(), theme.DIM)
            pygame.draw.rect(surface, theme.CARD_BG, RETRY_RECT,
                             border_radius=12)
            rs = theme.render("Try again", 14, theme.WHITE, bold=True)
            surface.blit(rs, rs.get_rect(center=RETRY_RECT.center))

    def _draw_synced(self, surface, r, active: int) -> None:
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, TOP + 22, 320, BOTTOM - TOP - 22))
        for i, (_t, text) in enumerate(r.lines):
            y = FOCUS_Y + (i - active) * LINE_H
            if y < TOP or y > BOTTOM:
                continue
            self._laid.append((i, y))
            if not text:
                continue
            if i == active:
                # the line being read is the one that must not be cut off, so
                # it wraps to a second row instead of truncating
                rows = _wrap(text, 15, True, _MAX_W)
                step = 18
                y0   = y - (len(rows) - 1) * step // 2
                for k, row in enumerate(rows):
                    s = theme.render(row, 15, theme.WHITE, bold=True,
                                     max_width=_MAX_W)
                    surface.blit(s, s.get_rect(centerx=160,
                                               centery=y0 + k * step))
            else:
                surf = self._line_surf(i, text, False)
                surface.blit(surf, surf.get_rect(centerx=160, centery=y))
        surface.set_clip(clip)

    def _draw_plain(self, surface, r) -> None:
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, TOP + 22, 320, BOTTOM - TOP - 22))
        y = TOP + 30 - int(self.scroll)
        for i, text in enumerate(r.plain.splitlines()):
            if TOP < y < BOTTOM and text.strip():
                surf = self._line_surf(i, text, False)
                surface.blit(surf, surf.get_rect(centerx=160, y=y))
            y += PLAIN_H
        surface.set_clip(clip)

    def _line_surf(self, i: int, text: str, active: bool) -> pygame.Surface:
        key = i if not active else -(i + 1)     # active variant cached apart
        hit = self._surfs.get(key)
        if hit is None:
            hit = theme.render(text, 15 if active else 13,
                               theme.WHITE if active else (120, 120, 135),
                               bold=active, max_width=_MAX_W)
            self._surfs[key] = hit
        return hit

    def _centre_text(self, surface, text: str, col) -> None:
        s = theme.render(text, 13, col, max_width=_MAX_W)
        surface.blit(s, s.get_rect(centerx=160, y=200))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.BACK

        r = self.result
        if not self.loading and (r is None or not r.found):
            if RETRY_RECT.collidepoint(x, y):
                self._start(force=True)
            return None

        if r is not None and r.synced:
            for i, ly in self._laid:
                if abs(y - ly) <= LINE_H // 2:
                    self.app.mpd.seek(r.lines[i][0])
                    self.app.request_poll()
                    return None
        return None

    def handle_scroll(self, dy: float) -> None:
        r = self.result
        if r is not None and r.found and not r.synced:
            n = len(r.plain.splitlines())
            self.scroll = max(0.0, min(self.scroll - dy,
                                       max(0.0, n * PLAIN_H - 300)))

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            self.app.pop()
