"""Browse screen — Artists → Albums → Tracks hierarchical browser."""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from pathlib import Path

import pygame

from musi.player import art_cache, audio_detect, icons, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.list_screen import ListScreen

ITEM_H  = 52          # height of each list row
LIST_Y  = 62          # top of the list (below statusbar + breadcrumb)
NAV_Y   = 456

# Albums level renders as a 2-column art grid instead of rows.
GRID_H     = 185      # height of one grid row (two album cells)
GRID_CELLS = ((10, 145), (165, 145))    # (x, w) of the two columns

# A-Z fast-scroll rail on the artists list.
RAIL_X       = 298    # touches right of this hit the rail
RAIL_LETTERS = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _letter_key(name: str) -> str:
    """Bucket an artist name for the A-Z rail; monotone in NOCASE sort order."""
    c = name.lstrip()[:1].upper()
    if "A" <= c <= "Z":
        return c
    if c and c < "A":
        return "#"    # digits / punctuation sort before letters
    return "~"        # non-latin names sort after Z


@dataclass
class _Item:
    label:    str
    sub:      str = ""    # subtitle — year (album) or track-number (track)
    row_id:   int = 0
    path:     str = ""
    art_path: str = ""


class BrowseScreen(ListScreen):

    def __init__(self, app) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=NAV_Y)
        self._level:       int         = 0
        self._artist_id:   int         = 0
        self._artist_name: str         = ""
        self._album_id:    int         = 0
        self._album_name:  str         = ""
        self._items:       list[_Item] = []

        # A-Z rail state (artists level)
        self._letter_keys: list[str] = []
        self._rail_active = False
        self._rail_letter = ""
        self._rail_surfs: list[pygame.Surface] | None = None

        # static surfaces
        self._nav_surf: pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        if self._level == 0:
            self._load_artists()

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf = theme.render(
                "Enter = select   Esc = back", 10, theme.WHITE
            )

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        # ── breadcrumb header ─────────────────────────────────────────────────
        if self._level == 0:
            crumb = "Browse"
        elif self._level == 1:
            crumb = self._artist_name
        else:
            crumb = self._album_name

        hdr_s = theme.render(crumb, 14, theme.WHITE, bold=True, max_width=196)
        surface.blit(hdr_s, (14, 26))

        if self._level > 0:
            # back arrow
            back_s = theme.render("‹ back", 10, theme.DIM)
            surface.blit(back_s, (320 - back_s.get_width() - 8, 30))

        # ── list (pixel-smooth with momentum) ─────────────────────────────────
        # Albums level packs two items per grid row.
        num_rows = (math.ceil(len(self._items) / 2) if self._level == 1
                    else len(self._items))
        self.draw_list_viewport(surface, num_rows)

        if self._level == 0 and self._items:
            self._draw_rail(surface)

        # ── empty state ───────────────────────────────────────────────────────
        if not self._items:
            msg = theme.render("Nothing here", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=220))

        # ── nav ───────────────────────────────────────────────────────────────
        surface.blit(self._nav_surf, self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        if self._level == 1:
            # Albums — one grid row = two album cells
            for col_i, (cx, cw) in enumerate(GRID_CELLS):
                idx = di * 2 + col_i
                if idx < len(self._items):
                    self._draw_album_cell(surface, cx, y, cw, idx)
            return

        item = self._items[di]
        sel  = (di == self._sel)
        # artists rows end short of the A-Z rail
        row_w = 284 if self._level == 0 else 298
        rect = pygame.Rect(10, y, row_w, ITEM_H - 3)

        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         rect, border_radius=7)

        col = theme.WHITE

        if self._level == 2:
            # Tracks — show track number badge
            bx, bcy = 16, y + (ITEM_H - 3) // 2
            pygame.draw.rect(surface, (50, 50, 68) if not sel else (80, 80, 110),
                             (bx, bcy - 12, 28, 24), border_radius=4)
            num_s = theme.render(
                item.sub.zfill(2) if item.sub else "·",
                10,
                theme.WHITE if sel else theme.DIM,
            )
            surface.blit(num_s, num_s.get_rect(center=(bx + 14, bcy)))

            lbl_s = theme.render(item.label, 13, col, bold=sel, max_width=226)
            surface.blit(lbl_s, (50, y + (ITEM_H - 3 - lbl_s.get_height()) // 2))

            # play icon on right
            icons.draw_play(surface, 302, bcy, theme.WHITE if sel else theme.DIM)
            return   # no chevron for tracks

        else:
            # Artists — name only
            lbl_s = theme.render(item.label, 13, col, bold=sel, max_width=250)
            surface.blit(lbl_s,
                         (16, y + (ITEM_H - 3 - lbl_s.get_height()) // 2))

        # chevron (artists)
        icons.draw_chevron_right(surface, rect.right - 14, y + (ITEM_H - 3) // 2,
                                 theme.WHITE if sel else theme.DIM)

    def _draw_album_cell(self, surface: pygame.Surface, x: int, y: int,
                         w: int, idx: int) -> None:
        item = self._items[idx]
        sel  = (idx == self._sel)
        rect = pygame.Rect(x, y, w, GRID_H - 6)
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         rect, border_radius=8)

        art_size = w - 16
        art = art_cache.load_art_thumbnail(item.art_path, art_size)
        if art:
            surface.blit(art, (x + 8, y + 8))
        else:
            pygame.draw.rect(surface, (40, 40, 55),
                             (x + 8, y + 8, art_size, art_size), border_radius=4)

        lbl_s = theme.render(item.label, 12, theme.WHITE, bold=sel,
                             max_width=art_size)
        surface.blit(lbl_s, (x + 8, y + art_size + 12))
        if item.sub:
            sub_s = theme.render(item.sub, 10,
                                 theme.WHITE if sel else theme.DIM)
            surface.blit(sub_s, (x + 8, y + art_size + 29))

    # ── A-Z fast-scroll rail (artists) ────────────────────────────────────────

    def _draw_rail(self, surface: pygame.Surface) -> None:
        if self._rail_surfs is None:
            self._rail_surfs = [theme.render(c, 9, theme.DIM)
                                for c in RAIL_LETTERS]
        span = (NAV_Y - 24) - LIST_Y
        step = span / len(RAIL_LETTERS)
        for i, s in enumerate(self._rail_surfs):
            surface.blit(s, s.get_rect(centerx=306,
                                       centery=int(LIST_Y + (i + 0.5) * step)))

        # big letter bubble while the finger is on the rail
        if self._rail_active and self._rail_letter:
            box = pygame.Rect(0, 0, 56, 56)
            box.center = (248, 240)
            pygame.draw.rect(surface, theme.CARD_BG, box, border_radius=12)
            pygame.draw.rect(surface, theme.ACCENT, box, 2, border_radius=12)
            big = theme.render(self._rail_letter, 26, theme.WHITE, bold=True)
            surface.blit(big, big.get_rect(center=box.center))

    def _rail_jump(self, y: int) -> None:
        span = (NAV_Y - 24) - LIST_Y
        frac = min(0.999, max(0.0, (y - LIST_Y) / span))
        letter = RAIL_LETTERS[int(frac * len(RAIL_LETTERS))]
        self._rail_letter = letter
        if letter == "#":
            idx = 0
        else:
            idx = bisect.bisect_left(self._letter_keys, letter)
        idx = max(0, min(idx, len(self._items) - 1))
        self._sel = idx
        self._klist.jump_to(idx)

    # ── input ─────────────────────────────────────────────────────────────────

    def on_press(self, x: int, y: int) -> bool:
        # A-Z rail captures the gesture so dragging scrubs by letter
        if (self._level == 0 and x >= RAIL_X and self._items
                and LIST_Y <= y < NAV_Y - 24):
            self._rail_active = True
            self._rail_jump(y)
            return True
        return False

    def on_drag(self, x: int, y: int) -> None:
        if self._rail_active:
            self._rail_jump(y)

    def on_release(self, x: int, y: int) -> None:
        self._rail_active = False

    def _clamp_scroll(self) -> None:
        row = self._sel // 2 if self._level == 1 else self._sel
        self._klist.ensure_visible(row)

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if not (LIST_Y <= y < NAV_Y - 24) or self._tap.pending:
            # "‹ back" hint in the header area
            if y < LIST_Y and x > 200 and self._level > 0:
                return Button.BACK
            return super().handle_touch(x, y)

        row_idx = self._klist.index_at(y - LIST_Y)
        if self._level == 1:
            col = 0 if x < 160 else 1
            di = row_idx * 2 + col
        else:
            di = row_idx

        if 0 <= di < len(self._items):
            self._sel = di                    # highlight flashes, then opens
            self._tap.set(self._select)
            return None

        return super().handle_touch(x, y)

    def handle_long_press(self, x: int, y: int) -> bool:
        if self._level == 0 or not (LIST_Y <= y < NAV_Y - 24):
            return False
        row_idx = self._klist.index_at(y - LIST_Y)
        if self._level == 1:
            col = 0 if x < 160 else 1
            di = row_idx * 2 + col
        else:
            di = row_idx

        if not (0 <= di < len(self._items)):
            return False
        self._sel = di
        item = self._items[di]
        if self._level == 2:
            self._open_track_menu(item)
        else:
            self._open_album_menu(item)
        return True



    def handle(self, button: Button, status: PlayerStatus) -> None:
        # In the album grid UP/DOWN move by a row (2), PREV/NEXT by a column.
        step = 2 if self._level == 1 else 1
        if button == Button.UP:
            self._sel = max(0, self._sel - step)
            self._clamp_scroll()
        elif button == Button.DOWN:
            self._sel = min(len(self._items) - 1, self._sel + step)
            self._clamp_scroll()
        elif button == Button.PREV and self._level == 1:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.NEXT and self._level == 1:
            self._sel = min(len(self._items) - 1, self._sel + 1)
            self._clamp_scroll()
        elif button == Button.SELECT:
            self._select()
        elif button == Button.PLAY_PAUSE:
            # From track list: play selected track
            if self._level == 2 and self._items:
                self._play_from(self._sel)
        elif button == Button.BACK:
            self._go_back()

    # ── navigation ────────────────────────────────────────────────────────────

    def _select(self) -> None:
        if not self._items:
            return
        item = self._items[self._sel]
        if self._level == 0:
            self._artist_id   = item.row_id
            self._artist_name = item.label
            self._level       = 1
            self._sel         = 0
            self._load_albums(item.row_id)
        elif self._level == 1:
            self._album_id   = item.row_id
            self._album_name = item.label
            self._level      = 2
            self._sel        = 0
            self._load_tracks(item.row_id)
        elif self._level == 2:
            self._play_from(self._sel)

    def _go_back(self) -> None:
        if self._level == 0:
            self.app.pop()
        elif self._level == 1:
            self._level = 0
            self._sel   = 0
            self._load_artists()
        elif self._level == 2:
            self._level = 1
            self._sel   = 0
            self._load_albums(self._artist_id)

    def _play_from(self, idx: int) -> None:
        paths = [item.path for item in self._items]
        self.app.mpd.play_paths(paths, start_index=idx)
        self.app.request_poll()
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))

    # ── long-press menus ──────────────────────────────────────────────────────

    def _open_track_menu(self, item: _Item) -> None:
        from musi.player.screens.context_menu import ContextMenuScreen
        idx = self._sel
        self.app.push(ContextMenuScreen(self.app, item.label, [
            ("Play now",     lambda: self._play_from(idx)),
            ("Play next",    lambda: self._queue([item.path], next_up=True)),
            ("Add to queue", lambda: self._queue([item.path], next_up=False)),
        ]))

    def _open_album_menu(self, item: _Item) -> None:
        from musi.player.screens.context_menu import ContextMenuScreen
        paths = self._album_paths(item.row_id)
        if not paths:
            return
        self.app.push(ContextMenuScreen(self.app, item.label, [
            ("Play album",   lambda: self._play_album(paths)),
            ("Play next",    lambda: self._queue(paths, next_up=True)),
            ("Add to queue", lambda: self._queue(paths, next_up=False)),
        ]))

    def _album_paths(self, album_id: int) -> list[str]:
        rows = self.app.db.execute(
            """SELECT path FROM tracks WHERE album_id = ?
               ORDER BY disc_number, track_number""",
            (album_id,),
        ).fetchall()
        return [r["path"] for r in rows]

    def _play_album(self, paths: list[str]) -> None:
        self.app.mpd.play_paths(paths)
        self.app.request_poll()
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))

    def _queue(self, paths: list[str], next_up: bool) -> None:
        if next_up:
            self.app.mpd.queue_next(paths)
        else:
            self.app.mpd.queue_add(paths)
        self.app.request_poll()

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_artists(self) -> None:
        self.item_h = ITEM_H
        self._klist.item_h = ITEM_H
        rows = self.app.db.execute(
            "SELECT id, name FROM artists ORDER BY name COLLATE NOCASE"
        ).fetchall()
        self._items = [_Item(label=r["name"], row_id=r["id"]) for r in rows]
        self._letter_keys = [_letter_key(r["name"]) for r in rows]
        self._klist.set_count(len(self._items), reset=True)

    def _load_albums(self, artist_id: int) -> None:
        self.item_h = GRID_H
        self._klist.item_h = GRID_H
        rows = self.app.db.execute(
            """SELECT al.id, al.title, al.year, al.art_path
               FROM albums al
               WHERE al.artist_id = ?
               ORDER BY al.year, al.title COLLATE NOCASE""",
            (artist_id,),
        ).fetchall()
        self._items = [
            _Item(
                label    = r["title"],
                sub      = str(r["year"]) if r["year"] else "",
                row_id   = r["id"],
                art_path = r["art_path"] or "",
            )
            for r in rows
        ]
        self._klist.set_count(math.ceil(len(self._items) / 2), reset=True)

    def _load_tracks(self, album_id: int) -> None:
        self.item_h = ITEM_H
        self._klist.item_h = ITEM_H
        rows = self.app.db.execute(
            """SELECT path, title, track_number
               FROM tracks
               WHERE album_id = ?
               ORDER BY disc_number, track_number""",
            (album_id,),
        ).fetchall()
        self._items = [
            _Item(
                label = r["title"] or Path(r["path"]).stem,
                sub   = str(r["track_number"]) if r["track_number"] else "",
                path  = r["path"],
            )
            for r in rows
        ]
        self._klist.set_count(len(self._items), reset=True)









