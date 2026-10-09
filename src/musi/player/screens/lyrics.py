"""Lyrics — Apple Music style: big left-aligned lines over the album's colours.

Opened from Now Playing. The fetch runs once per track on a worker thread and
is cached on disk (library/lyrics.py); if the song changes while the screen is
open, it follows along.

  - The current line is bright, the rest dimmed; the view glides (eased, not
    jumped) to keep the current line near the top third.
  - Word-synced songs (LRCLIB Lyricsfile) fill word by word, each word lit
    left to right over its own duration. Line-synced songs light the whole
    line, which is always exactly in time.
  - Instrumental breaks ("♪" / blank lines) show three breathing dots.
  - Drag to read ahead; it snaps back to the song a few seconds later.
    Tap a line to jump there.

Pi notes: nothing here scales or alpha-blends a layer per frame. Words are
pre-rendered twice (dim / bright) and the "fill" is the bright one blitted
with a clipped source rect; dots are plain circles. See blit.py for why.
"""
from __future__ import annotations

import math
import threading
import time

import pygame

from musi.library import lyrics as lyrics_lib
from musi.player import art_cache, audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

TOP         = 26                 # below the status bar
HEADER_H    = 56                 # art + title band
VIEW_TOP    = TOP + HEADER_H     # lyrics are clipped to start here
BOTTOM      = 480
FOCUS_Y     = 150                # where the current line's top settles
ACTIVE_SIZE = 20
LINE_SIZE   = 20                 # same size: lines never reflow when they light
ROW_GAP     = 2                  # between wrapped rows of one lyric
LINE_GAP    = 18                 # between lyrics
GAP_H       = 22                 # height of an instrumental "• • •" line
PLAIN_H     = 30                 # plain-lyric line pitch
MARGIN      = 20
RETRY_RECT  = pygame.Rect(90, 300, 140, 48)
RESUME_S    = 3.0                # after a manual drag, snap back this much later
EASE        = 9.0                # scroll easing rate (higher = snappier)

_MAX_W = 320 - 2 * MARGIN
DIM    = (128, 128, 140)
BRIGHT = theme.WHITE


def _is_gap(text: str) -> bool:
    return not text.strip() or text.strip() in ("♪", "♫", "...", "…")


class _Laid:
    """One lyric, laid out once: its rows (or word placements) and height."""

    def __init__(self, line: lyrics_lib.Line) -> None:
        self.line = line
        self.gap = _is_gap(line.text)
        self.rtl = theme.is_rtl(line.text)
        self.rows: list[str] = []
        self.row_surfs: list[tuple[pygame.Surface, pygame.Surface]] = []  # (dim, bright)
        self.words: list[tuple[int, int, pygame.Surface, pygame.Surface, lyrics_lib.Word]] = []
        self.height = GAP_H
        self.top = 0.0                              # y within the whole sheet
        if self.gap:
            return
        f = theme.font(LINE_SIZE, True)
        row_h = f.get_linesize()
        if line.words and not self.rtl:
            # place each word; wrap when the next one would overflow
            x = y = 0
            rows: list[list[str]] = [[]]
            breakable = False           # only wrap where the text has a space:
            for w in line.words:        # NetEase splits "don’t" into 3 tokens
                ww = f.size(w.text)[0]
                if breakable and x + f.size(w.text.rstrip())[0] > _MAX_W:
                    x, y = 0, y + row_h + ROW_GAP
                    rows.append([])
                breakable = w.text[-1:].isspace()
                dim = theme.render(w.text, LINE_SIZE, DIM, bold=True)
                bright = theme.render(w.text, LINE_SIZE, BRIGHT, bold=True)
                self.words.append((x, y, dim, bright, w))
                rows[-1].append(w.text)
                x += ww
            self.rows = ["".join(r).strip() for r in rows]
            self.height = y + row_h
        else:
            self.rows = theme.wrap(line.text, LINE_SIZE, True, _MAX_W)
            self.row_surfs = [(theme.render(r, LINE_SIZE, DIM, bold=True, max_width=_MAX_W),
                               theme.render(r, LINE_SIZE, BRIGHT, bold=True, max_width=_MAX_W))
                              for r in self.rows]
            self.height = sum(s.get_height() for s, _ in self.row_surfs) \
                + ROW_GAP * (len(self.row_surfs) - 1)


class LyricsScreen(Screen):

    # Reading lyrics involves no touching, so the usual inactivity timeouts
    # would blank the panel mid-song. 0 disables both.
    dim_after = 0
    off_after = 0

    def __init__(self, app, status: PlayerStatus) -> None:
        super().__init__(app)
        self._set_track(status)
        self.loading = False
        self.result: lyrics_lib.Lyrics | None = None
        self.scroll  = 0.0                   # plain lyrics: finger scroll
        self._thread: threading.Thread | None = None
        self._layout: list[_Laid] = []
        self._view = 0.0                     # synced: sheet y at VIEW_TOP
        self._manual_until = 0.0
        self._last_t = time.monotonic()
        self._bg: pygame.Surface | None = None
        self._bg_key: str | None = None
        self._head: tuple[pygame.Surface | None, pygame.Surface, pygame.Surface] | None = None
        self._moving = False
        self._live = False                   # word fill / dots need full FPS
        # (index, y centre, height) of each lyric drawn last frame
        self._laid: list[tuple[int, float, float]] = []

    def _set_track(self, status) -> None:
        self.artist   = getattr(status, "artist", "") or ""
        self.title    = getattr(status, "title", "") or ""
        self.album    = getattr(status, "album", "") or ""
        self.duration = float(getattr(status, "duration", 0.0) or 0.0)
        self.path     = getattr(status, "path", "") or ""

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        if self.result is None and not self.loading:
            self._start(force=False)

    @property
    def animates(self) -> bool:
        return self.loading or self._moving or self._live

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
        self._set_track(status)
        self.result  = None
        self.scroll  = 0.0
        self._layout = []
        self._head   = None
        self._start(force=False)

    def _start(self, *, force: bool) -> None:
        if self.loading:
            return
        self.loading = True
        self._layout = []

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
        """The wrapped rows a lyric was laid out as."""
        return self._layout[index].rows if 0 <= index < len(self._layout) else []

    def _ensure_layout(self) -> None:
        r = self.result
        if self._layout or r is None or not r.synced:
            return
        timed = r.timed or lyrics_lib.timed_from_lrc(r.lines)
        y = 0.0
        for line in timed:
            laid = _Laid(line)
            laid.top = y
            y += laid.height + LINE_GAP
            self._layout.append(laid)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        self._follow(status)
        now = time.monotonic()
        dt, self._last_t = min(0.1, now - self._last_t), now
        self._moving = self._live = False

        surface.blit(self._background(), (0, 0))
        r = self.result
        self._laid = []

        if self.loading:
            self._centre_text(surface, "Loading lyrics…", DIM)
        elif r is not None and r.synced:
            self._ensure_layout()
            self._draw_synced(surface, status, dt, now)
        elif r is not None and r.found:
            self._draw_plain(surface, r)
        else:
            self._centre_text(surface, self.message(), DIM)
            pygame.draw.rect(surface, (255, 255, 255), RETRY_RECT, 2, border_radius=24)
            rs = theme.render("Try again", 14, theme.WHITE, bold=True)
            surface.blit(rs, rs.get_rect(center=RETRY_RECT.center))

        self._draw_header(surface)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)

    def _draw_synced(self, surface, status, dt: float, now: float) -> None:
        elapsed = float(getattr(status, "elapsed", 0.0) or 0.0)
        active = self.active_at(status)
        anchor = max(0, active)
        if self._layout and now >= self._manual_until:
            target = self._layout[anchor].top - (FOCUS_Y - VIEW_TOP)
            gap = target - self._view
            if abs(gap) > 0.5:
                self._view += gap * min(1.0, dt * EASE) if dt > 0 else gap
                self._moving = True
            else:
                self._view = target
        playing = getattr(status, "state", "") == "play"

        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, VIEW_TOP, 320, BOTTOM - VIEW_TOP))
        for i, laid in enumerate(self._layout):
            top = VIEW_TOP + laid.top - self._view
            if top > BOTTOM:
                break
            if top + laid.height < VIEW_TOP:
                continue
            self._laid.append((i, top + laid.height / 2, laid.height))
            is_active = i == active
            if laid.gap:
                self._draw_dots(surface, int(top), is_active and playing, now)
                self._live |= is_active and playing
            elif laid.words:
                self._draw_words(surface, laid, int(top), elapsed if is_active else None)
                self._live |= is_active and playing
            else:
                self._draw_rows(surface, laid, int(top), is_active)
        surface.set_clip(clip)

    def _draw_rows(self, surface, laid: _Laid, top: int, bright: bool) -> None:
        y = top
        for dim, lit in laid.row_surfs:
            s = lit if bright else dim
            x = 320 - MARGIN - s.get_width() if laid.rtl else MARGIN
            surface.blit(s, (x, y))
            y += s.get_height() + ROW_GAP

    def _draw_words(self, surface, laid: _Laid, top: int, t: float | None) -> None:
        """Word-synced line. ``t`` is playback time if this is the current
        line (words fill as they're sung), None for every other line."""
        for x, y, dim, lit, w in laid.words:
            pos = (MARGIN + x, top + y)
            if t is None or t < w.start:
                surface.blit(dim, pos)
            elif t >= w.end:
                surface.blit(lit, pos)
            else:
                surface.blit(dim, pos)
                frac = (t - w.start) / max(0.05, w.end - w.start)
                width = int(lit.get_width() * frac)
                if width > 0:
                    surface.blit(lit, pos, pygame.Rect(0, 0, width, lit.get_height()))

    def _draw_dots(self, surface, top: int, live: bool, now: float) -> None:
        cy = top + GAP_H // 2
        for k in range(3):
            if live:
                # each dot breathes in turn
                phase = math.sin(now * 3.0 - k * 0.7) * 0.5 + 0.5
                r = 3 + int(round(2 * phase))
                col = theme.WHITE
            else:
                r, col = 3, DIM
            pygame.draw.circle(surface, col, (MARGIN + 5 + k * 16, cy), r)

    def _draw_plain(self, surface, r) -> None:
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, VIEW_TOP, 320, BOTTOM - VIEW_TOP))
        y = VIEW_TOP + 8 - int(self.scroll)
        for text in r.plain.splitlines():
            if not text.strip():
                y += PLAIN_H // 2
                continue
            for row in theme.wrap(text, 17, True, _MAX_W):
                if VIEW_TOP - PLAIN_H < y < BOTTOM:
                    s = theme.render(row, 17, theme.WHITE, bold=True, max_width=_MAX_W)
                    rtl = theme.is_rtl(row)
                    surface.blit(s, (320 - MARGIN - s.get_width() if rtl else MARGIN, y))
                y += PLAIN_H
        surface.set_clip(clip)

    def _centre_text(self, surface, text: str, col) -> None:
        s = theme.render(text, 13, col, max_width=_MAX_W)
        surface.blit(s, s.get_rect(centerx=160, y=200))

    # ── background + header ───────────────────────────────────────────────────

    def _background(self) -> pygame.Surface:
        """The album's blurred backdrop, darkened — built once per track."""
        if self._bg is not None and self._bg_key == self.path:
            return self._bg
        self._bg_key = self.path
        bg = pygame.Surface((320, 480))
        bg.fill(theme.BG)
        accent = theme.ACCENT
        db = getattr(self.app, "db", None)
        if db is not None and self.path:
            try:
                res = art_cache.get_track_art_and_palette(db, self.path, self.artist, self.album)
                accent = art_cache.parse_palette(res.get("palette"))
                back = art_cache.load_surface(res.get("backdrop_path") or "", (320, 480))
                if back is not None:
                    bg.blit(back, (0, 0))
                else:
                    _gradient(bg, accent)
            except Exception:
                _gradient(bg, accent)
        else:
            _gradient(bg, accent)
        shade = pygame.Surface((320, 480))
        shade.fill((0, 0, 0))
        shade.set_alpha(110)
        bg.blit(shade, (0, 0))               # opaque onto opaque — Pi-safe
        self._bg = bg
        return bg

    def _draw_header(self, surface) -> None:
        """Small art + title/artist band; lyrics scroll away beneath it."""
        if self._head is None:
            art = None
            db = getattr(self.app, "db", None)
            if db is not None and self.path:
                try:
                    res = art_cache.get_track_art_and_palette(db, self.path, self.artist, self.album)
                    art = art_cache.load_surface(res.get("art_path") or "", (40, 40))
                except Exception:
                    art = None
            self._head = (art,
                          theme.render(self.title or "Lyrics", 13, theme.WHITE, bold=True,
                                       max_width=240),
                          theme.render(self.artist, 11, DIM, max_width=240))
        art, title, artist = self._head
        # re-cover the band with the background so scrolled lines vanish under it
        surface.blit(self._background(), (0, TOP), pygame.Rect(0, TOP, 320, HEADER_H))
        if art is not None:
            surface.blit(art, (MARGIN - 6, TOP + 8))
        else:
            pygame.draw.rect(surface, (60, 60, 75), (MARGIN - 6, TOP + 8, 40, 40), border_radius=6)
        surface.blit(title, (MARGIN + 44, TOP + 10))
        surface.blit(artist, (MARGIN + 44, TOP + 29))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < TOP:
            return Button.HOME

        r = self.result
        if not self.loading and (r is None or not r.found):
            if RETRY_RECT.collidepoint(x, y):
                self._start(force=True)
            return None

        if r is not None and r.synced and y >= VIEW_TOP:
            for i, ly, h in self._laid:
                if abs(y - ly) <= max(h, 20) / 2 + LINE_GAP / 2:
                    self.app.mpd.seek(self._layout[i].line.start if self._layout
                                      else r.lines[i][0])
                    self._manual_until = 0.0         # follow the song again
                    self.app.request_poll()
                    return None
        return None

    def handle_scroll(self, dy: float) -> None:
        r = self.result
        if r is None or not r.found:
            return
        if r.synced:
            if self._layout:
                last = self._layout[-1].top
                self._view = max(-(FOCUS_Y - VIEW_TOP), min(self._view - dy, last))
            self._manual_until = time.monotonic() + RESUME_S
        else:
            n = len(r.plain.splitlines())
            self.scroll = max(0.0, min(self.scroll - dy,
                                       max(0.0, n * PLAIN_H - 300)))

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            self.app.pop()


def _gradient(surface: pygame.Surface, accent: tuple) -> None:
    """Fallback background (radio, no art): the accent fading to near-black."""
    top = theme.darken(accent, 0.55)
    for y in range(0, 480, 4):
        k = y / 480
        col = tuple(int(c * (1 - k) + b * k) for c, b in zip(top, theme.BG))
        surface.fill(col, (0, y, 320, 4))
