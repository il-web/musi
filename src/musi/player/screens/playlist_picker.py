"""Add-to-playlist picker — pushed from a track's long-press menu.

Lists the stored playlists with a "New playlist…" row on top. Picking one adds
the carried tracks to it and pops; "New" prompts for a name first.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, icons, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus

LIST_Y = 64
NAV_Y  = 462
ITEM_H = 52
_NEW   = "＋New playlist…"      # ＋New playlist…


class AddToPlaylistScreen(ListScreen):

    def __init__(self, app, paths: list[str]) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=NAV_Y)
        self._paths = list(paths)
        self._rows: list[str] = []          # _NEW, then playlist names
        self._counts: dict[str, int] = {}
        self._hdr: pygame.Surface | None = None

    def on_enter(self) -> None:
        pls = self.app.mpd.list_playlists()
        self._rows = [_NEW] + [p.name for p in pls]
        self._counts = {p.name: p.track_count for p in pls}
        self._klist.set_count(len(self._rows), reset=True)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr = theme.render("Add to playlist", 16, theme.WHITE, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(self._hdr, (14, 26))

        self.draw_list_viewport(surface, len(self._rows))

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        name = self._rows[di]
        sel  = (di == self._sel)
        rect = pygame.Rect(10, y, 300, ITEM_H - 4)
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         rect, border_radius=8)

        is_new = (di == 0)
        label  = "New playlist" if is_new else name
        if is_new:
            _draw_plus(surface, 30, y + (ITEM_H - 4) // 2,
                       theme.WHITE if sel else theme.ACCENT)
        elif name == "Favorites":
            icons.draw_heart(surface, 30, y + (ITEM_H - 4) // 2,
                             theme.WHITE if sel else theme.ACCENT, filled=True)
        lbl = theme.render(label, 14, theme.WHITE, bold=sel, max_width=210)
        surface.blit(lbl, (52, y + (ITEM_H - 4 - lbl.get_height()) // 2))

        if not is_new:
            n = self._counts.get(name, 0)
            cnt = theme.render(f"{n}", 11, theme.WHITE if sel else theme.DIM)
            surface.blit(cnt, cnt.get_rect(right=298,
                                           centery=y + (ITEM_H - 4) // 2))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < statusbar.BAR_H:
            return Button.HOME
        if LIST_Y <= y < NAV_Y and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self._rows):
                self._sel = di
                self._tap.set(lambda: self._pick(di))
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.DOWN:
            self._sel = min(len(self._rows) - 1, self._sel + 1)
            self._clamp_scroll()
        elif button == Button.SELECT:
            self._pick(self._sel)
        elif button == Button.BACK:
            self.app.pop()

    def _pick(self, di: int) -> None:
        if di == 0:
            from musi.player.screens.text_entry import TextEntryScreen
            self.app.push(TextEntryScreen(
                self.app, "New playlist", on_commit=self._create))
            return
        self.app.mpd.playlist_add(self._rows[di], self._paths)
        self.app.pop()

    def _create(self, name: str) -> None:
        self.app.mpd.playlist_add(name, self._paths)
        self.app.pop()          # leave the picker too — back to the origin screen


def _draw_plus(surface, cx, cy, col) -> None:
    pygame.draw.line(surface, col, (cx - 7, cy), (cx + 7, cy), 2)
    pygame.draw.line(surface, col, (cx, cy - 7), (cx, cy + 7), 2)
