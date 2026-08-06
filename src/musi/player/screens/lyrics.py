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
FOCUS_Y    = 236                # the active line's centre
ACTIVE_SIZE = 19                # the line being sung
LINE_SIZE   = 16                # everything else
ROW_GAP     = 3                 # between wrapped rows of one lyric
LINE_GAP    = 13                # between lyrics
PLAIN_H    = 26                 # plain-lyric line pitch
RETRY_RECT = pygame.Rect(90, 300, 140, 48)

_MAX_W = 300


def _wrap(text: str, size: int, bold: bool, max_w: int) -> list[str]:
    """Word-wrap into as many rows as it takes. Nothing is ever truncated.

    A single word wider than max_w is left long — theme.render will clip it,
    which beats dropping it.
    """
    font = theme.font(size, bold)
    if not text or font.size(text)[0] <= max_w:
        return [text]
    rows: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and font.size(trial)[0] > max_w:
            rows.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        rows.append(cur)
    return rows or [text]


class LyricsScreen(Screen):

    # Reading lyrics involves no touching, so the usual inactivity timeouts
    # would blank the panel mid-song. 0 disables both (app.py:284, app.py:315).
    dim_after = 0
    off_after = 0

    def __init__(self, app, status: PlayerStatus) -> None:
        super().__init__(app)
        self.artist   = getattr(status, "artist", "") or ""
        self.title    = getattr(status, "title", "") or ""
        self.album    = getattr(status, "album", "") or ""
        self.duration = float(getattr(status, "duration", 0.0) or 0.0)
        self.path     = getattr(status, "path", "") or ""

        self.loading = False
        self.result: lyrics_lib.Lyrics | None = None
        self.scroll  = 0.0            # plain-lyrics finger scroll
        self._thread: threading.Thread | None = None
        self._surfs: dict[tuple[int, bool], list[pygame.Surface]] = {}
        self._rows:  dict[tuple[int, bool], list[str]] = {}
        self._hdr: pygame.Surface | None = None
        # (index, y centre, height) of each lyric drawn last frame
        self._laid: list[tuple[int, float, float]] = []

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

    def _follow(self, status: PlayerStatus) -> None:
        """Re-point at whatever is playing now, if the track changed.

        An empty path (stopped, or a gap between tracks) is ignored — blanking
        the words the moment playback pauses would be worse than keeping them.
        """
        path = getattr(status, "path", "") or ""
        if not path or path == self.path:
            return
        self.path     = path
        self.artist   = getattr(status, "artist", "") or ""
        self.title    = getattr(status, "title", "") or ""
        self.album    = getattr(status, "album", "") or ""
        self.duration = float(getattr(status, "duration", 0.0) or 0.0)
        self.result   = None
        self.scroll   = 0.0
        self._hdr     = None
        self._rows.clear()
        self._start(force=False)

    def _start(self, *, force: bool) -> None:
        if self.loading:
            return
        self.loading = True
        self._surfs.clear()
        self._rows.clear()

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
        for i, y, _h in self._laid:
            if i == index:
                return int(y)
        return None

    def rows_for(self, index: int) -> list[str]:
        """The wrapped rows a lyric was last laid out as."""
        for key in ((index, True), (index, False)):
            if key in self._rows:
                return self._rows[key]
        return []

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        self._follow(status)

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
        """Lay lines out from the active one outward.

        Heights vary because any line may wrap to several rows, so positions
        accumulate from the focus point rather than sitting on a fixed pitch.
        """
        n = len(r.lines)
        anchor = active if active >= 0 else 0
        heights = {}

        def height(i: int) -> float:
            if i not in heights:
                heights[i] = self._line_height(i, r.lines[i][1], i == active)
            return heights[i]

        # centre y of each line, walking out from the anchor in both directions
        centres: dict[int, float] = {anchor: float(FOCUS_Y)}
        y = FOCUS_Y
        for i in range(anchor - 1, -1, -1):
            y -= (height(i + 1) + height(i)) / 2 + LINE_GAP
            centres[i] = y
            if y < TOP - 60:
                break
        y = FOCUS_Y
        for i in range(anchor + 1, n):
            y += (height(i - 1) + height(i)) / 2 + LINE_GAP
            centres[i] = y
            if y > BOTTOM + 60:
                break

        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, TOP + 20, 320, BOTTOM - TOP - 20))
        for i, cy in sorted(centres.items()):
            h = height(i)
            if cy + h / 2 < TOP or cy - h / 2 > BOTTOM:
                continue
            self._laid.append((i, cy, h))
            surfs = self._line_surfs(i, r.lines[i][1], i == active)
            top = cy - h / 2
            for s in surfs:
                surface.blit(s, s.get_rect(centerx=160, y=int(top)))
                top += s.get_height() + ROW_GAP
        surface.set_clip(clip)

    def _line_surfs(self, i: int, text: str,
                    active: bool) -> list[pygame.Surface]:
        """Rendered rows for one lyric, cached per (index, active)."""
        key = (i, active)
        hit = self._surfs.get(key)
        if hit is None:
            size = ACTIVE_SIZE if active else LINE_SIZE
            rows = _wrap(text, size, active, _MAX_W)
            self._rows[key] = rows
            hit = [theme.render(row, size,
                                theme.WHITE if active else (125, 125, 140),
                                bold=active, max_width=_MAX_W)
                   for row in rows]
            self._surfs[key] = hit
        return hit

    def _line_height(self, i: int, text: str, active: bool) -> float:
        surfs = self._line_surfs(i, text, active)
        if not surfs:
            return float(LINE_SIZE)
        return sum(s.get_height() for s in surfs) + ROW_GAP * (len(surfs) - 1)

    def _draw_plain(self, surface, r) -> None:
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, TOP + 22, 320, BOTTOM - TOP - 22))
        y = TOP + 30 - int(self.scroll)
        for i, text in enumerate(r.plain.splitlines()):
            for s in self._line_surfs(i, text, False):
                if TOP < y < BOTTOM and text.strip():
                    surface.blit(s, s.get_rect(centerx=160, y=y))
                y += PLAIN_H
        surface.set_clip(clip)

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
            for i, ly, h in self._laid:
                if abs(y - ly) <= max(h, 20) / 2 + LINE_GAP / 2:
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
