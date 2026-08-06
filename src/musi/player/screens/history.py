"""History screen showing recently played or most played tracks."""

import pygame

from musi.player import art_cache, audio_detect, icons, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus

ITEM_H = 52
LIST_Y = 62      # default top of the list
NAV_Y = 456      # default bottom of the content area


class HistoryScreen(ListScreen):
    def __init__(self, app, mode: str = "recent",
                 list_y: int = LIST_Y, nav_y: int = NAV_Y) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=list_y, nav_y=nav_y)
        self._mode = mode  # "recent" or "most"
        self._items = []

        # static surfaces
        title = "Recently Played" if mode == "recent" else "Most Played"
        self._header_surf = theme.render(title, 16, theme.WHITE, bold=True)

    def on_enter(self) -> None:
        self._load_items()

    def _load_items(self) -> None:
        if self._mode == "recent":
            rows = self.app.db.execute(
                """SELECT t.path, t.title, ar.name as artist, al.art_path
                   FROM play_history ph
                   JOIN tracks t ON ph.track_id = t.id
                   JOIN artists ar ON t.artist_id = ar.id
                   JOIN albums al ON t.album_id = al.id
                   ORDER BY ph.played_at DESC
                   LIMIT 100"""
            ).fetchall()
        else:
            rows = self.app.db.execute(
                """SELECT t.path, t.title, ar.name as artist, al.art_path, COUNT(ph.id) as score
                   FROM play_history ph
                   JOIN tracks t ON ph.track_id = t.id
                   JOIN artists ar ON t.artist_id = ar.id
                   JOIN albums al ON t.album_id = al.id
                   GROUP BY t.id
                   ORDER BY score DESC, MAX(ph.played_at) DESC
                   LIMIT 100"""
            ).fetchall()

        self._items = [dict(r) for r in rows]
        self._klist.set_count(len(self._items), reset=True)

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=True)
        surface.blit(self._header_surf, (14, 26))

        self.draw_list_viewport(surface, len(self._items))

        if not self._items:
            msg = theme.render("No play history yet", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=240))

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        item = self._items[di]
        sel = (di == self._sel)
        rect = pygame.Rect(10, y, 298, ITEM_H - 3)

        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG, rect, border_radius=8)

        # art thumbnail
        art = art_cache.load_art_thumbnail(item["art_path"])
        if art:
            surface.blit(art, (16, y + 3))
            tx = 68
            max_w = 200
        else:
            tx = 20
            max_w = 250

        title_s = theme.render(item["title"], 13, theme.WHITE, bold=True, max_width=max_w)
        surface.blit(title_s, (tx, y + 8))

        sub_s = theme.render(item["artist"], 11, theme.DIM, max_width=max_w)
        surface.blit(sub_s, (tx, y + 26))

        if sel:
            icons.draw_play(surface, 302, y + (ITEM_H - 3) // 2, theme.WHITE)

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 40:
            return Button.BACK
        if self.list_y <= y < self.nav_y - 24 and not self._tap.pending:
            di = self._klist.index_at(y - self.list_y)
            if 0 <= di < len(self._items):
                self._sel = di
                self._tap.set(lambda: self._play_item(self._items[self._sel]))
                return None
        return super().handle_touch(x, y)

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (self.list_y <= y < self.nav_y - 24):
            return False
        di = self._klist.index_at(y - self.list_y)
        if not (0 <= di < len(self._items)):
            return False
        self._sel = di
        item = self._items[di]
        from musi.player.screens.context_menu import ContextMenuScreen
        self.app.push(ContextMenuScreen(self.app, item["title"], [
            ("Play now",     lambda: self._play_item(item)),
            ("Play next",    lambda: self._queue(item, next_up=True)),
            ("Add to queue", lambda: self._queue(item, next_up=False)),
        ]))
        return True

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.DOWN:
            self._sel = min(len(self._items) - 1, self._sel + 1)
            self._clamp_scroll()
        elif button == Button.SELECT and self._items:
            self._play_item(self._items[self._sel])
        elif button == Button.BACK:
            self.app.pop()

    def _play_item(self, item: dict) -> None:
        self.app.mpd.play_paths([item["path"]])
        self.app.request_poll()
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))

    def _queue(self, item: dict, next_up: bool) -> None:
        if next_up:
            self.app.mpd.queue_next([item["path"]])
        else:
            self.app.mpd.queue_add([item["path"]])
        self.app.request_poll()
