"""Search screen — full-text search across the music library."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

# ── layout constants ──────────────────────────────────────────────────────────
BAR_H   = 26          # status bar height (matches statusbar.BAR_H)
BOX_Y   = BAR_H + 4  # search box top
BOX_H   = 36          # search box height
LIST_Y  = BOX_Y + BOX_H + 4   # 70 — first result top
ITEM_H  = 54          # height per result row
NAV_Y   = 456         # nav hint y
MAX_VIS = (NAV_Y - LIST_Y) // ITEM_H  # ≈ 7

_CURSOR_BLINK = 0.55   # seconds per blink half-cycle


@dataclass
class _Result:
    title:  str
    artist: str
    album:  str
    path:   str


class SearchScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._query:   str           = ""
        self._results: list[_Result] = []
        self._sel:     int           = 0
        self._scroll:  int           = 0
        self._scroll_px: float       = 0.0   # accumulated drag for swipe-scroll
        self._enter_t: float         = 0.0

        # static surfaces (lazy)
        self._nav_surf: pygame.Surface | None = None
        self._ph_surf:  pygame.Surface | None = None  # placeholder

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._query   = ""
        self._results = []
        self._sel     = 0
        self._scroll  = 0
        self._enter_t = time.monotonic()

    # ── raw event (keyboard typing) ───────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_BACKSPACE:
            if self._query:
                self._query = self._query[:-1]
                self._search()
                return True   # consumed — do NOT also fire Button.BACK
            return False      # empty → let BACK pop the screen
        if event.unicode and event.unicode.isprintable():
            self._query += event.unicode
            self._search()
            return True
        return False

    # ── touch input ──────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if LIST_Y <= y < NAV_Y - 24:
            vi = (y - LIST_Y) // ITEM_H
            di = vi + self._scroll
            if 0 <= di < len(self._results):
                self._sel = di
                self._clamp_scroll()
                self._play_selected()
                return None
        return super().handle_touch(x, y)

    def handle_scroll(self, dy: float) -> None:
        max_scroll = len(self._results) - MAX_VIS
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

    # ── button input ─────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            if self._sel > 0:
                self._sel -= 1
                self._clamp_scroll()
        elif button == Button.DOWN:
            if self._sel < len(self._results) - 1:
                self._sel += 1
                self._clamp_scroll()
        elif button in (Button.SELECT, Button.PLAY_PAUSE):
            self._play_selected()
        elif button == Button.BACK:
            if self._query:
                self._query   = ""
                self._results = []
                self._sel     = 0
                self._scroll  = 0
            else:
                self.app.pop()

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf = theme.render(
                "Enter = play   Esc = clear/back", 10, theme.WHITE
            )
        if self._ph_surf is None:
            self._ph_surf = theme.render("Type to search…", 12, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        # ── search box ────────────────────────────────────────────────────────
        box_rect = pygame.Rect(8, BOX_Y, 304, BOX_H)
        pygame.draw.rect(surface, (28, 28, 42), box_rect, border_radius=6)
        pygame.draw.rect(surface, theme.ACCENT, box_rect, 1, border_radius=6)

        # search icon (magnifier)
        _magnifier(surface, 22, BOX_Y + BOX_H // 2, theme.DIM)

        if self._query:
            # cursor blink
            t = time.monotonic() - self._enter_t
            show_cursor = int(t / _CURSOR_BLINK) % 2 == 0
            display_text = self._query + ("|" if show_cursor else " ")
            txt_s = theme.render(display_text, 12, theme.WHITE, max_width=268)
            surface.blit(txt_s, (38, BOX_Y + (BOX_H - txt_s.get_height()) // 2))
        else:
            surface.blit(self._ph_surf,
                         (38, BOX_Y + (BOX_H - self._ph_surf.get_height()) // 2))

        # ── results / idle state ──────────────────────────────────────────────
        if not self._results and self._query:
            msg = theme.render("No results", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=240))
        elif not self._results:
            hint = theme.render("Search by title, artist, or album",
                                11, theme.DIM, max_width=290)
            surface.blit(hint, hint.get_rect(centerx=160, y=240))
        else:
            for vi in range(MAX_VIS):
                di = vi + self._scroll
                if di >= len(self._results):
                    break
                self._draw_result(surface, vi, di)

            if len(self._results) > MAX_VIS:
                _scrollbar(surface, 314, LIST_Y, NAV_Y - LIST_Y,
                           len(self._results), self._scroll, MAX_VIS)

        # ── result count (top-right of box) ───────────────────────────────────
        if self._results:
            n    = len(self._results)
            word = "result" if n == 1 else "results"
            cnt_s = theme.render(f"{n} {word}", 10, theme.DIM)
            surface.blit(cnt_s, cnt_s.get_rect(right=310, y=BOX_Y + 2))

        # ── nav hint ──────────────────────────────────────────────────────────
        surface.blit(self._nav_surf,
                     self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    def _draw_result(self, surface: pygame.Surface, vi: int, di: int) -> None:
        res  = self._results[di]
        y    = LIST_Y + vi * ITEM_H
        sel  = (di == self._sel)
        rect = pygame.Rect(8, y, 304, ITEM_H - 3)

        pygame.draw.rect(
            surface,
            theme.ACCENT if sel else theme.CARD_BG,
            rect,
            border_radius=7,
        )

        # title
        title_s = theme.render(res.title, 13, theme.WHITE,
                               bold=sel, max_width=278)
        surface.blit(title_s, (16, y + 8))

        # artist · album subtitle
        if res.artist and res.album:
            meta_str = f"{res.artist}  ·  {res.album}"
        elif res.artist:
            meta_str = res.artist
        else:
            meta_str = res.album
        if meta_str:
            meta_s = theme.render(meta_str, 10,
                                  theme.WHITE if sel else theme.DIM,
                                  max_width=278)
            surface.blit(meta_s, (16, y + 29))

        # small play triangle on the right when selected
        if sel:
            _play_icon(surface, 302, y + (ITEM_H - 3) // 2, theme.WHITE)

    # ── search logic ─────────────────────────────────────────────────────────

    def _search(self) -> None:
        self._sel    = 0
        self._scroll = 0
        q = self._query.strip()
        if not q:
            self._results = []
            return

        # FTS5 prefix-match: each word becomes "word"*
        words      = q.split()
        match_expr = " ".join(f'"{w}"*' for w in words)

        try:
            rows = self.app.db.execute(
                """SELECT t.path, t.title, ar.name AS artist, al.title AS album
                   FROM tracks t
                   JOIN albums  al ON al.id = t.album_id
                   JOIN artists ar ON ar.id = al.artist_id
                   JOIN (
                       SELECT rowid FROM tracks_fts WHERE tracks_fts MATCH ?
                   ) fts ON fts.rowid = t.id
                   LIMIT 50""",
                (match_expr,),
            ).fetchall()
        except Exception:
            # FTS syntax error (e.g. mid-typing a quote) — show nothing
            self._results = []
            return

        self._results = [
            _Result(
                title  = r["title"] or Path(r["path"]).stem,
                artist = r["artist"] or "",
                album  = r["album"] or "",
                path   = r["path"],
            )
            for r in rows
        ]

    # ── playback ─────────────────────────────────────────────────────────────

    def _play_selected(self) -> None:
        if not self._results:
            return
        paths = [r.path for r in self._results]
        self.app.mpd.play_paths(paths, start_index=self._sel)
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))

    # ── scroll ────────────────────────────────────────────────────────────────

    def _clamp_scroll(self) -> None:
        if self._sel < self._scroll:
            self._scroll = self._sel
        elif self._sel >= self._scroll + MAX_VIS:
            self._scroll = self._sel - MAX_VIS + 1


# ── drawing helpers ───────────────────────────────────────────────────────────

def _magnifier(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    pygame.draw.circle(surface, col, (cx - 1, cy - 1), 5, 2)
    pygame.draw.line(surface, col, (cx + 3, cy + 3), (cx + 7, cy + 7), 2)


def _play_icon(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    pts = [(cx - 5, cy - 6), (cx - 5, cy + 6), (cx + 6, cy)]
    pygame.draw.polygon(surface, col, pts)


def _scrollbar(
    surface: pygame.Surface,
    x: int, y: int, h: int,
    total: int, scroll: int, vis: int,
) -> None:
    pygame.draw.rect(surface, (30, 30, 44), (x, y, 2, h), border_radius=1)
    thumb_h = max(16, int(h * vis / total))
    thumb_y = y + int((h - thumb_h) * scroll / max(1, total - vis))
    pygame.draw.rect(surface, theme.DIM, (x, thumb_y, 2, thumb_h), border_radius=1)
