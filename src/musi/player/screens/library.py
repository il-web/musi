"""Library — pill filters over an album grid and an artist list.

Albums render as a 3-column art grid with labels below the covers. Labels sit
BELOW the art, never over it: 9px text over arbitrary album art is unreadable
on light sleeves, and a caption band across twelve covers is clutter.

Artists render as ROWS, not a grid — the artists table is id + name, with no
art to show. PILLS is a list so playlists become one entry later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from musi.player import (album_queries, art_cache, audio_detect, backdrop,
                         icons, statusbar, theme)
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus

LIST_Y = 98
NAV_Y  = 406

MARGIN, GAP, COLS = 12, 8, 3
CELL   = (320 - MARGIN * 2 - GAP * (COLS - 1)) // COLS   # 93
TEXT_H = 28
ROW_H  = CELL + TEXT_H + GAP                             # 129
ARTIST_H = 52

TITLE_Y, PILL_Y, PILL_H = 34, 66, 24
PILLS = ["Albums", "Artists"]


@dataclass
class _Item:
    label:    str
    sub:      str = ""
    row_id:   int = 0
    art_path: str = ""


class LibraryScreen(ListScreen):

    def __init__(self, app, list_y: int = LIST_Y, nav_y: int = NAV_Y) -> None:
        super().__init__(app, item_h=ROW_H, list_y=list_y, nav_y=nav_y)
        self.pill = 0
        self.items: list[_Item] = []
        self._pill_rects: list[pygame.Rect] = []
        self.artist_id   = 0        # non-zero while drilled into one artist
        self.artist_name = ""

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._load()

    def set_pill(self, i: int) -> None:
        if i == self.pill or not (0 <= i < len(PILLS)):
            return
        self.pill = i
        self._sel = 0
        self.artist_id, self.artist_name = 0, ""
        self._load()

    def _load(self) -> None:
        """All the screen's SQL, once per pill change."""
        if self.pill == 0:
            rows = album_queries.all_albums(self.app.db)
            self.items = [_Item(r["title"], str(r["year"] or ""), r["id"],
                                r["art_path"] or "") for r in rows]
            self.item_h = self._klist.item_h = ROW_H
            self._klist.set_count(math.ceil(len(self.items) / COLS), reset=True)
        else:
            rows = album_queries.all_artists(self.app.db)
            self.items = [_Item(r["name"], row_id=r["id"]) for r in rows]
            self.item_h = self._klist.item_h = ARTIST_H
            self._klist.set_count(len(self.items), reset=True)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        bg, _accent = backdrop.for_track(self.app.db, status)
        if bg:
            surface.blit(bg, (0, 0))
        else:
            surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)

        if self.artist_id:
            icons.draw_chevron_left(surface, 18, TITLE_Y + 10, theme.ACCENT)
            surface.blit(theme.render(self.artist_name, 18, theme.WHITE,
                                      bold=True, max_width=264),
                         (34, TITLE_Y))
            self._pill_rects = []       # no pills while drilled in
        else:
            surface.blit(theme.render("Library", 20, theme.WHITE, bold=True),
                         (MARGIN, TITLE_Y))
            self._draw_pills(surface)

        rows = (math.ceil(len(self.items) / COLS) if self.pill == 0
                else len(self.items))
        self.draw_list_viewport(surface, rows)

        if not self.items:
            msg = theme.render("Nothing here", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=220))

    def _draw_pills(self, surface: pygame.Surface) -> None:
        self._pill_rects = []
        x = MARGIN
        for i, label in enumerate(PILLS):
            on  = (i == self.pill)
            lbl = theme.render(label, 11, theme.BG if on else theme.DIM, bold=on)
            rect = pygame.Rect(x, PILL_Y, lbl.get_width() + 24, PILL_H)
            if on:
                pygame.draw.rect(surface, theme.ACCENT, rect, border_radius=12)
            else:
                pygame.draw.rect(surface, (70, 70, 88), rect, 1, border_radius=12)
            surface.blit(lbl, lbl.get_rect(center=rect.center))
            self._pill_rects.append(rect)
            x = rect.right + 8

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        if self.pill == 1:
            self._draw_artist_row(surface, y, di)
            return
        for col in range(COLS):
            idx = di * COLS + col
            if idx < len(self.items):
                self._draw_cell(surface, MARGIN + col * (CELL + GAP), y, idx)

    def _draw_cell(self, surface, x, y, idx) -> None:
        item = self.items[idx]
        art  = art_cache.load_art_thumbnail(item.art_path, CELL)
        if art:
            surface.blit(art, (x, y))
        else:
            pygame.draw.rect(surface, (40, 40, 55), (x, y, CELL, CELL),
                             border_radius=4)
        surface.blit(theme.render(item.label, 10, theme.WHITE, max_width=CELL),
                     (x, y + CELL + 4))
        if item.sub:
            surface.blit(theme.render(item.sub, 9, theme.DIM, max_width=CELL),
                         (x, y + CELL + 16))

    def _draw_artist_row(self, surface, y, di) -> None:
        item = self.items[di]
        sel  = (di == self._sel)
        rect = pygame.Rect(MARGIN, y, 320 - MARGIN * 2, ARTIST_H - 3)
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         rect, border_radius=7)
        lbl = theme.render(item.label, 13, theme.WHITE, bold=sel, max_width=250)
        surface.blit(lbl, (rect.x + 12,
                           y + (ARTIST_H - 3 - lbl.get_height()) // 2))
        icons.draw_chevron_right(surface, rect.right - 14,
                                 y + (ARTIST_H - 3) // 2,
                                 theme.WHITE if sel else theme.DIM)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if self.artist_id and y < PILL_Y and x < 120:
            self.go_up()
            return None

        for i, rect in enumerate(self._pill_rects):
            if rect.collidepoint(x, y):
                self.set_pill(i)
                return None

        if not (self.list_y <= y < self.nav_y) or self._tap.pending:
            return super().handle_touch(x, y)

        row = self._klist.index_at(y - self.list_y)
        if self.pill == 0:
            col = min(COLS - 1, max(0, (x - MARGIN) // (CELL + GAP)))
            di  = row * COLS + col
        else:
            di = row

        if 0 <= di < len(self.items):
            self._sel = di
            self._tap.set(self._select)
            return None
        return super().handle_touch(x, y)

    def _select(self) -> None:
        item = self.items[self._sel]
        if self.pill == 0:
            from musi.player.screens.album import AlbumScreen
            self.app.push(AlbumScreen(self.app, item.row_id))
        else:
            self._drill_into_artist(item.row_id, item.label)

    # ── artist drill-in (a level inside Library, not a new screen) ─────────────

    def _drill_into_artist(self, artist_id: int, name: str) -> None:
        """Show one artist's albums as the grid, with a back crumb.

        This is a level within Library rather than a pushed screen: the nav row
        stays, and the grid drawing is already here. It replaces browse.py's
        level 1.
        """
        self.artist_id   = artist_id
        self.artist_name = name
        self._sel = 0
        rows = album_queries.albums_by_artist(self.app.db, artist_id)
        self.items = [_Item(r["title"], str(r["year"] or ""), r["id"],
                            r["art_path"] or "") for r in rows]
        self.item_h = self._klist.item_h = ROW_H
        self._klist.set_count(math.ceil(len(self.items) / COLS), reset=True)

    def go_up(self) -> None:
        """Leave the artist's albums for the artist list."""
        if self.artist_id:
            self.artist_id = 0
            self.artist_name = ""
            self._sel = 0
            self._load()
