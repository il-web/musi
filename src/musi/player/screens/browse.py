"""Browse screen — Artists → Albums → Tracks hierarchical browser."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

ITEM_H  = 52          # height of each list row
LIST_Y  = 62          # top of the list (below statusbar + breadcrumb)
NAV_Y   = 456
MAX_VIS = (NAV_Y - LIST_Y) // ITEM_H    # rows that fit on screen (~7)


@dataclass
class _Item:
    label:    str
    sub:      str = ""    # subtitle — year (album) or track-number (track)
    row_id:   int = 0
    path:     str = ""
    art_path: str = ""


class BrowseScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._level:       int         = 0
        self._artist_id:   int         = 0
        self._artist_name: str         = ""
        self._album_id:    int         = 0
        self._album_name:  str         = ""
        self._items:       list[_Item] = []
        self._sel:         int         = 0
        self._scroll:      int         = 0
        self._scroll_px:   float       = 0.0   # accumulated drag for swipe-scroll

        # tiny album-art cache: art_path → 36×36 Surface (or None)
        self._art_cache: dict[str, pygame.Surface | None] = {}

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

        # ── list ──────────────────────────────────────────────────────────────
        for vi in range(MAX_VIS):
            di = vi + self._scroll
            if di >= len(self._items):
                break
            self._draw_item(surface, vi, di)

        # ── scrollbar ─────────────────────────────────────────────────────────
        if len(self._items) > MAX_VIS:
            _scrollbar(surface, 315, LIST_Y, NAV_Y - LIST_Y,
                       len(self._items), self._scroll, MAX_VIS)

        # ── empty state ───────────────────────────────────────────────────────
        if not self._items:
            msg = theme.render("Nothing here", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=220))

        # ── nav ───────────────────────────────────────────────────────────────
        surface.blit(self._nav_surf, self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    def _draw_item(self, surface: pygame.Surface, vi: int, di: int) -> None:
        item = self._items[di]
        y    = LIST_Y + vi * ITEM_H
        sel  = (di == self._sel)
        rect = pygame.Rect(10, y, 298, ITEM_H - 3)

        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         rect, border_radius=7)

        col = theme.WHITE

        if self._level == 1:
            # Albums — show art thumbnail on left
            art = self._get_art(item.art_path)
            if art:
                surface.blit(art, (16, y + 3))
                tx = 68
            else:
                # placeholder rect
                pygame.draw.rect(surface, (40, 40, 55),
                                 (16, y + 3, 46, 46), border_radius=3)
                tx = 68

            # title + year
            lbl_s = theme.render(item.label, 13, col, bold=sel, max_width=210)
            surface.blit(lbl_s, (tx, y + 6))
            if item.sub:
                sub_s = theme.render(item.sub, 10, theme.WHITE if sel else theme.DIM)
                surface.blit(sub_s, (tx, y + 26))

        elif self._level == 2:
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
            _play_icon(surface, 302, bcy, theme.WHITE if sel else theme.DIM)
            return   # no chevron for tracks

        else:
            # Artists — name only
            lbl_s = theme.render(item.label, 13, col, bold=sel, max_width=266)
            surface.blit(lbl_s,
                         (16, y + (ITEM_H - 3 - lbl_s.get_height()) // 2))

        # chevron (artists + albums)
        _chevron(surface, 302, y + (ITEM_H - 3) // 2,
                 theme.WHITE if sel else theme.DIM)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if LIST_Y <= y < NAV_Y - 24:
            vi = (y - LIST_Y) // ITEM_H
            di = vi + self._scroll
            if 0 <= di < len(self._items):
                self._sel = di
                self._clamp_scroll()
                self._select()
                return None
        # "‹ back" hint in top-right header area
        if y < 58 and x > 200 and self._level > 0:
            return Button.BACK
        return super().handle_touch(x, y)

    def handle_scroll(self, dy: float) -> None:
        max_scroll = len(self._items) - MAX_VIS
        if max_scroll <= 0:
            return
        self._scroll_px += -dy
        while self._scroll_px >= ITEM_H and self._scroll < max_scroll:
            self._scroll_px -= ITEM_H
            self._scroll += 1
        while self._scroll_px <= -ITEM_H and self._scroll > 0:
            self._scroll_px += ITEM_H
            self._scroll -= 1
        if (self._scroll == 0 and self._scroll_px < 0) or \
           (self._scroll >= max_scroll and self._scroll_px > 0):
            self._scroll_px = 0

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.DOWN:
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
            self._scroll      = 0
            self._load_albums(item.row_id)
        elif self._level == 1:
            self._album_id   = item.row_id
            self._album_name = item.label
            self._level      = 2
            self._sel        = 0
            self._scroll     = 0
            self._load_tracks(item.row_id)
        elif self._level == 2:
            self._play_from(self._sel)

    def _go_back(self) -> None:
        if self._level == 0:
            self.app.pop()
        elif self._level == 1:
            self._level  = 0
            self._sel    = 0
            self._scroll = 0
            self._load_artists()
        elif self._level == 2:
            self._level  = 1
            self._sel    = 0
            self._scroll = 0
            self._load_albums(self._artist_id)

    def _play_from(self, idx: int) -> None:
        paths = [item.path for item in self._items]
        self.app.mpd.play_paths(paths, start_index=idx)
        self.app.request_poll()
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_artists(self) -> None:
        rows = self.app.db.execute(
            "SELECT id, name FROM artists ORDER BY name COLLATE NOCASE"
        ).fetchall()
        self._items = [_Item(label=r["name"], row_id=r["id"]) for r in rows]

    def _load_albums(self, artist_id: int) -> None:
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

    def _load_tracks(self, album_id: int) -> None:
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

    def _get_art(self, art_path: str) -> pygame.Surface | None:
        if art_path in self._art_cache:
            return self._art_cache[art_path]
        result = None
        if art_path and Path(art_path).exists():
            try:
                img    = pygame.image.load(art_path).convert()
                result = pygame.transform.scale(img, (46, 46))
            except Exception:
                pass
        self._art_cache[art_path] = result
        return result



    def _clamp_scroll(self) -> None:
        if self._sel < self._scroll:
            self._scroll = self._sel
        elif self._sel >= self._scroll + MAX_VIS:
            self._scroll = self._sel - MAX_VIS + 1


# ── drawing helpers ───────────────────────────────────────────────────────────

def _chevron(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    pts = [(cx - 4, cy - 6), (cx + 2, cy), (cx - 4, cy + 6)]
    pygame.draw.lines(surface, col, False, pts, 2)


def _play_icon(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    pts = [(cx - 5, cy - 6), (cx - 5, cy + 6), (cx + 6, cy)]
    pygame.draw.polygon(surface, col, pts)


def _scrollbar(
    surface: pygame.Surface,
    x: int, y: int, h: int,
    total: int, scroll: int, vis: int,
) -> None:
    """Thin scrollbar on the right edge."""
    pygame.draw.rect(surface, (30, 30, 44), (x, y, 2, h), border_radius=1)
    thumb_h = max(16, int(h * vis / total))
    thumb_y = y + int((h - thumb_h) * scroll / max(1, total - vis))
    pygame.draw.rect(surface, theme.DIM, (x, thumb_y, 2, thumb_h), border_radius=1)
