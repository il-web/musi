"""Home — a greeting and shelves of album art.

A shelf with no rows is NOT drawn. play_history is empty on every fresh
install, so a naive Home would greet a new user with two empty strips. On
first boot only "New in your library" has rows, and it works from file_mtime
the moment music lands.

All three queries run in on_enter. draw() must stay free of SQL.

Three full-size shelves are taller than the content band, so the shelf region
(FIRST_Y..nav_y) scrolls vertically; the greeting stays a fixed header. A
single gesture is axis-locked on the first slop of movement: it either drags
one shelf horizontally or scrolls the page vertically, never both.
"""
from __future__ import annotations

from datetime import datetime

import pygame

from musi.player import (album_queries, art_cache, audio_detect, backdrop,
                         statusbar, theme)
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import Shelf

LIST_Y = 26
NAV_Y  = 406

CELL   = 93          # album cover edge — matches library.CELL so the art
                     # thumbnail cache is keyed once, not twice, per cover
GAP    = 10
MARGIN = 12
TEXT_H = 30          # title + artist under a cover
LABEL_H = 20         # shelf heading
SHELF_H = LABEL_H + CELL + TEXT_H + 8

GREET_Y = 34
FIRST_Y = 86

_SLOP = 12         # matches app.TAP_SLOP_PX — movement below this is a tap

_SHELVES = [
    ("Recently played",     album_queries.recently_played),
    ("New in your library", album_queries.recently_added),
    ("Most played",         album_queries.most_played),
]


def greeting(hour: int) -> str:
    """Time-of-day greeting. Boundaries: 5, 12, 18, 22."""
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    if 18 <= hour < 22:
        return "Good evening"
    return "Good night"


class HomeScreen(Screen):

    def __init__(self, app, list_y: int = LIST_Y, nav_y: int = NAV_Y) -> None:
        super().__init__(app)
        self.list_y = list_y
        self.nav_y  = nav_y
        self.shelves: list[tuple[str, list, Shelf]] = []
        self._greet_surf: pygame.Surface | None = None
        self._greet_text = ""
        self._moving = False

        # vertical scroll of the shelf region (greeting is a fixed header)
        self._view_h = self.nav_y - FIRST_Y
        self._scroll = 0.0
        self._max_scroll = 0.0

        # captured gesture: which shelf, where it started, and its locked axis
        self._drag: "Shelf | None" = None
        self._drag_rows: list = []
        self._axis: "str | None" = None
        self._press_x = 0
        self._press_y = 0
        self._last_x  = 0
        self._last_y  = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._load()

    def _load(self) -> None:
        """All the screen's SQL, once. Empty shelves are dropped here."""
        self.shelves = []
        for title, query in _SHELVES:
            rows = query(self.app.db)
            if not rows:
                continue
            shelf = Shelf(item_w=CELL, gap=GAP, view_w=320 - MARGIN)
            shelf.set_count(len(rows), reset=True)
            self.shelves.append((title, rows, shelf))

        self._scroll = 0.0
        view_h = self.nav_y - FIRST_Y
        self._view_h = view_h
        self._max_scroll = max(0.0, len(self.shelves) * SHELF_H - view_h)

    @property
    def is_empty(self) -> bool:
        return not self.shelves

    @property
    def animates(self) -> bool:
        """Read-only. update() is called from draw — never from here, or a
        coasting shelf would advance twice per frame."""
        return self._moving

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        self._moving = False
        for _, _, shelf in self.shelves:
            if shelf.update():
                self._moving = True

        bg, _accent = backdrop.for_track(self.app.db, status)
        if bg:
            surface.blit(bg, (0, 0))
        else:
            surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)

        if self.is_empty:
            self._draw_empty(surface)
            return

        self._draw_greeting(surface)

        region = pygame.Rect(0, FIRST_Y, 320, self._view_h)
        clip = surface.get_clip()
        surface.set_clip(region)
        for i, (title, rows, shelf) in enumerate(self.shelves):
            y = FIRST_Y + i * SHELF_H - self._scroll
            if y >= region.bottom or y + SHELF_H <= region.top:
                continue
            self._draw_shelf(surface, y, title, rows, shelf, region)
        surface.set_clip(clip)

    def _draw_greeting(self, surface: pygame.Surface) -> None:
        text = greeting(datetime.now().hour)
        if text != self._greet_text:
            self._greet_text = text
            self._greet_surf = theme.render(text, 21, theme.WHITE, bold=True)
        surface.blit(self._greet_surf, (MARGIN, GREET_Y))

    def _draw_shelf(self, surface, y, title, rows, shelf, region) -> None:
        surface.blit(theme.render_cached(title, 12, theme.WHITE, bold=True),
                     (MARGIN, y))
        ay = y + LABEL_H

        hband = pygame.Rect(MARGIN, int(ay), 320 - MARGIN, CELL + TEXT_H)
        surface.set_clip(hband.clip(region))
        first = shelf.first_visible()
        shift = shelf.pixel_shift()
        for vi in range(shelf.visible_cols()):
            di = first + vi
            if di >= len(rows):
                break
            x = MARGIN + vi * shelf.pitch - shift
            self._draw_cell(surface, x, ay, rows[di])
        surface.set_clip(region)

    def _draw_cell(self, surface, x, y, row) -> None:
        art = art_cache.load_art_thumbnail(row["art_path"] or "", CELL)
        if art:
            surface.blit(art, (x, y))
        else:
            pygame.draw.rect(surface, (40, 40, 55), (x, y, CELL, CELL),
                             border_radius=4)
        surface.blit(
            theme.render_cached(row["title"], 10, theme.WHITE, max_width=CELL),
            (x, y + CELL + 5))
        surface.blit(
            theme.render_cached(row["artist"], 9, theme.DIM, max_width=CELL),
            (x, y + CELL + 18))

    def _draw_empty(self, surface: pygame.Surface) -> None:
        a = theme.render("No music yet", 15, theme.WHITE, bold=True)
        surface.blit(a, a.get_rect(centerx=160, y=200))
        b = theme.render("Add tracks over Wi-Fi transfer", 11, theme.DIM)
        surface.blit(b, b.get_rect(centerx=160, y=226))

    # ── input ─────────────────────────────────────────────────────────────────

    def _clamp_scroll(self) -> None:
        self._scroll = max(0.0, min(self._max_scroll, self._scroll))

    def _shelf_at(self, y: int):
        """(rows, shelf, art_top_y) for the shelf whose art band contains y.

        Uses the same ``- self._scroll`` offset draw() uses, so a tap lands on
        the shelf that is actually under the finger once the page is scrolled.
        """
        if y < FIRST_Y or y >= self.nav_y:
            return None
        for i, (_, rows, shelf) in enumerate(self.shelves):
            ay = FIRST_Y + i * SHELF_H - self._scroll + LABEL_H
            if ay <= y < ay + CELL:
                return rows, shelf, ay
        return None

    def handle_touch(self, x: int, y: int) -> "Button | None":
        """Taps outside a shelf only. Taps on a shelf are resolved in
        on_release, because on_press captures the gesture.

        A status-bar tap is BACK — the host paints the ‹ chevron whenever the
        stack is deeper than one, and Library/Search already return it. Do NOT
        defer to super(): its y > 430 branch returns SELECT/PLAY_PAUSE, which is
        unreachable under the host and wrong if Home is ever drawn standalone.
        """
        if y < 26:
            return Button.BACK
        return None

    def on_press(self, x: int, y: int) -> bool:
        """Capture the gesture. Returning True routes motion to on_drag and the
        release to on_release, bypassing the app's tap/scroll plumbing — the
        same trick the launcher uses. The axis is locked on first movement in
        on_drag; a gesture that never passes _SLOP is a tap.
        """
        found = self._shelf_at(y)
        if not found:
            return False
        rows, shelf, _ = found
        self._drag, self._drag_rows = shelf, rows
        self._axis = None
        self._press_x = self._last_x = x
        self._press_y = self._last_y = y
        shelf.start_touch()
        return True

    def on_drag(self, x: int, y: int) -> None:
        if self._drag is None:
            return
        if self._axis is None:
            if max(abs(x - self._press_x), abs(y - self._press_y)) >= _SLOP:
                self._axis = ("h" if abs(x - self._press_x) >= abs(y - self._press_y)
                              else "v")
        if self._axis == "h":
            self._drag.drag_by(x - self._last_x)
        elif self._axis == "v":
            self._scroll -= y - self._last_y
            self._clamp_scroll()
        self._last_x = x
        self._last_y = y

    def on_release(self, x: int, y: int) -> None:
        if self._drag is None:
            return
        shelf, rows = self._drag, self._drag_rows
        shelf.end_touch()
        axis = self._axis
        self._drag, self._drag_rows, self._axis = None, [], None

        if axis is None:                       # never passed the slop → a tap
            di = shelf.index_at(x - MARGIN)
            if 0 <= di < len(rows):
                from musi.player.screens.album import AlbumScreen
                self.app.push(AlbumScreen(self.app, rows[di]["id"]))

    def handle_scroll(self, dy: float) -> None:
        """Vertical drag that started off a shelf band still scrolls the page.
        Positive dy = finger moved down; content follows the finger."""
        self._scroll -= dy
        self._clamp_scroll()
