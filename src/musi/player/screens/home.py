"""Home — a greeting and shelves of album art.

A shelf with no rows is NOT drawn. play_history is empty on every fresh
install, so a naive Home would greet a new user with two empty strips. On
first boot only "New in your library" has rows, and it works from file_mtime
the moment music lands.

All three queries run in on_enter. draw() must stay free of SQL.
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

CELL   = 92          # album cover edge
GAP    = 10
MARGIN = 12
TEXT_H = 30          # title + artist under a cover
LABEL_H = 20         # shelf heading
SHELF_H = LABEL_H + CELL + TEXT_H + 8

GREET_Y = 34
SUB_Y   = 63
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
        # captured horizontal gesture: which shelf, and where it started
        self._drag: "Shelf | None" = None
        self._drag_rows: list = []
        self._press_x = 0
        self._press_y = 0
        self._last_x  = 0

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
        y = FIRST_Y
        for title, rows, shelf in self.shelves:
            if y >= self.nav_y:
                break
            self._draw_shelf(surface, y, title, rows, shelf)
            y += SHELF_H

    def _draw_greeting(self, surface: pygame.Surface) -> None:
        text = greeting(datetime.now().hour)
        if text != self._greet_text:
            self._greet_text = text
            self._greet_surf = theme.render(text, 21, theme.WHITE, bold=True)
        surface.blit(self._greet_surf, (MARGIN, GREET_Y))

    def _draw_shelf(self, surface, y, title, rows, shelf) -> None:
        surface.blit(theme.render(title, 12, theme.WHITE, bold=True),
                     (MARGIN, y))
        ay = y + LABEL_H

        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(MARGIN, ay, 320 - MARGIN, CELL + TEXT_H))
        first = shelf.first_visible()
        shift = shelf.pixel_shift()
        for vi in range(shelf.visible_cols()):
            di = first + vi
            if di >= len(rows):
                break
            x = MARGIN + vi * shelf.pitch - shift
            self._draw_cell(surface, x, ay, rows[di])
        surface.set_clip(clip)

    def _draw_cell(self, surface, x, y, row) -> None:
        art = art_cache.load_art_thumbnail(row["art_path"] or "", CELL)
        if art:
            surface.blit(art, (x, y))
        else:
            pygame.draw.rect(surface, (40, 40, 55), (x, y, CELL, CELL),
                             border_radius=4)
        surface.blit(theme.render(row["title"], 10, theme.WHITE, max_width=CELL),
                     (x, y + CELL + 5))
        surface.blit(theme.render(row["artist"], 9, theme.DIM, max_width=CELL),
                     (x, y + CELL + 18))

    def _draw_empty(self, surface: pygame.Surface) -> None:
        a = theme.render("No music yet", 15, theme.WHITE, bold=True)
        surface.blit(a, a.get_rect(centerx=160, y=200))
        b = theme.render("Add tracks over Wi-Fi transfer", 11, theme.DIM)
        surface.blit(b, b.get_rect(centerx=160, y=226))

    # ── input ─────────────────────────────────────────────────────────────────

    def _shelf_at(self, y: int):
        """(rows, shelf, top_y) for the shelf whose art band contains y."""
        sy = FIRST_Y
        for _, rows, shelf in self.shelves:
            ay = sy + LABEL_H
            if ay <= y < ay + CELL:
                return rows, shelf, ay
            sy += SHELF_H
        return None

    def handle_touch(self, x: int, y: int) -> "Button | None":
        """Taps outside a shelf only. Taps on a shelf are resolved in
        on_release, because on_press captures the gesture for scrolling."""
        return None

    def on_press(self, x: int, y: int) -> bool:
        """Capture the gesture so a horizontal flick scrolls the shelf.

        Returning True routes motion to on_drag and the release to on_release,
        bypassing the app's tap/scroll plumbing — the same trick the launcher
        uses. Tap-vs-drag is then resolved on release against _SLOP.
        """
        found = self._shelf_at(y)
        if not found:
            return False
        rows, shelf, _ = found
        self._drag, self._drag_rows = shelf, rows
        self._press_x = self._last_x = x
        self._press_y = y
        shelf.start_touch()
        return True

    def on_drag(self, x: int, y: int) -> None:
        if self._drag is None:
            return
        self._drag.drag_by(x - self._last_x)
        self._last_x = x

    def on_release(self, x: int, y: int) -> None:
        if self._drag is None:
            return
        shelf, rows = self._drag, self._drag_rows
        moved = abs(x - self._press_x) > _SLOP or abs(y - self._press_y) > _SLOP
        shelf.end_touch()
        self._drag, self._drag_rows = None, []

        if not moved:
            di = shelf.index_at(x - MARGIN)
            if 0 <= di < len(rows):
                from musi.player.screens.album import AlbumScreen
                self.app.push(AlbumScreen(self.app, rows[di]["id"]))

    def handle_scroll(self, dy: float) -> None:
        """Home is one screenful by design — nothing scrolls vertically."""
