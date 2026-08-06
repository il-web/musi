"""Album screen — Apple-Music-style album page (art, info, play/shuffle)."""
from __future__ import annotations

import random

import pygame

from musi.player import art_cache, audio_detect, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus

ITEM_H = 48
LIST_Y = 264
NAV_Y  = minibar.BAR_Y

ART_SIZE = 120
ART_Y    = 34

PLAY_RECT    = pygame.Rect(24, 216, 176, 42)
SHUFFLE_RECT = pygame.Rect(208, 216, 88, 42)


def _fmt_total(seconds: float) -> str:
    m = int(seconds // 60)
    if m >= 60:
        return f"{m // 60} hr {m % 60} min"
    return f"{m} min" if m else "<1 min"


class AlbumScreen(ListScreen):

    def __init__(self, app, album_id: int) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=NAV_Y)
        self._album_id = album_id

        self._album_title = ""
        self._artist_name = ""
        self._sub_line    = ""      # "Artist · 2025"
        self._meta_line   = ""      # "12 songs · 43 min"
        self._tracks: list[dict] = []
        self._accent = theme.ACCENT
        self._art:  pygame.Surface | None = None

        # static surfaces (lazy)
        self._title_surf: pygame.Surface | None = None
        self._sub_surf:   pygame.Surface | None = None
        self._meta_surf:  pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        album = self.app.db.execute(
            """SELECT al.title, al.year, al.art_path, al.palette,
                      ar.name AS artist
               FROM albums al JOIN artists ar ON ar.id = al.artist_id
               WHERE al.id = ?""",
            (self._album_id,),
        ).fetchone()
        if not album:
            return
        self._album_title = album["title"]
        self._artist_name = album["artist"]
        self._sub_line = (f"{album['artist']} · {album['year']}"
                          if album["year"] else album["artist"])
        self._art    = art_cache.load_surface(album["art_path"] or "",
                                              (ART_SIZE, ART_SIZE))
        self._accent = art_cache.parse_palette(album["palette"] or "",
                                               do_brighten=True)

        rows = self.app.db.execute(
            """SELECT path, title, track_number, duration
               FROM tracks WHERE album_id = ?
               ORDER BY disc_number, track_number""",
            (self._album_id,),
        ).fetchall()
        self._tracks = [dict(r) for r in rows]
        total = sum(r["duration"] or 0 for r in self._tracks)
        n = len(self._tracks)
        self._meta_line = f"{n} song{'s' if n != 1 else ''} · {_fmt_total(total)}"
        self._klist.set_count(n, reset=True)

        # rebuild text surfaces with fresh data
        self._title_surf = self._sub_surf = self._meta_surf = None

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._title_surf is None:
            self._title_surf = theme.render(self._album_title, 15, theme.WHITE,
                                            bold=True, max_width=300)
            self._sub_surf   = theme.render(self._sub_line, 11, theme.DIM,
                                            max_width=300)
            self._meta_surf  = theme.render(self._meta_line, 10, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)

        # ── art ───────────────────────────────────────────────────────────────
        ax = (320 - ART_SIZE) // 2
        if self._art:
            surface.blit(self._art, (ax, ART_Y))
        else:
            pygame.draw.rect(surface, (40, 40, 55),
                             (ax, ART_Y, ART_SIZE, ART_SIZE), border_radius=6)
            icons.draw_music_note(surface, 160, ART_Y + ART_SIZE // 2,
                                  (80, 80, 100))

        # ── texts ─────────────────────────────────────────────────────────────
        surface.blit(self._title_surf,
                     self._title_surf.get_rect(centerx=160, y=160))
        surface.blit(self._sub_surf,
                     self._sub_surf.get_rect(centerx=160, y=182))
        surface.blit(self._meta_surf,
                     self._meta_surf.get_rect(centerx=160, y=199))

        # ── buttons ───────────────────────────────────────────────────────────
        pygame.draw.rect(surface, self._accent, PLAY_RECT, border_radius=21)
        icons.draw_play(surface, PLAY_RECT.x + 62, PLAY_RECT.centery, theme.WHITE)
        play_s = theme.render("Play", 13, theme.WHITE, bold=True)
        surface.blit(play_s, play_s.get_rect(x=PLAY_RECT.x + 78,
                                             centery=PLAY_RECT.centery))

        pygame.draw.rect(surface, theme.CARD_BG, SHUFFLE_RECT, border_radius=21)
        pygame.draw.rect(surface, self._accent, SHUFFLE_RECT, 1, border_radius=21)
        _draw_shuffle(surface, SHUFFLE_RECT.centerx, SHUFFLE_RECT.centery,
                      self._accent)

        # ── track list ────────────────────────────────────────────────────────
        self.draw_list_viewport(surface, len(self._tracks))

        if not self._tracks:
            msg = theme.render("No tracks", 12, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=LIST_Y + 40))

        minibar.draw(surface, self.app, status)

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        t   = self._tracks[di]
        sel = (di == self._sel)
        rect = pygame.Rect(10, y, 298, ITEM_H - 3)
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         rect, border_radius=7)

        bx, bcy = 16, y + (ITEM_H - 3) // 2
        pygame.draw.rect(surface, (80, 80, 110) if sel else (50, 50, 68),
                         (bx, bcy - 11, 26, 22), border_radius=4)
        num = str(t["track_number"]).zfill(2) if t["track_number"] else "·"
        num_s = theme.render(num, 10, theme.WHITE if sel else theme.DIM)
        surface.blit(num_s, num_s.get_rect(center=(bx + 13, bcy)))

        lbl = theme.render(t["title"], 12, theme.WHITE, bold=sel, max_width=228)
        surface.blit(lbl, (50, y + (ITEM_H - 3 - lbl.get_height()) // 2))
        icons.draw_play(surface, 300, bcy, theme.WHITE if sel else theme.DIM)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return None

        if PLAY_RECT.collidepoint(x, y):
            self._play_album(shuffle=False)
            return None
        if SHUFFLE_RECT.collidepoint(x, y):
            self._play_album(shuffle=True)
            return None
        if LIST_Y <= y < NAV_Y - 24 and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self._tracks):
                self._sel = di
                self._tap.set(lambda: self._play_from(di))
                return None
        return super().handle_touch(x, y)

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (LIST_Y <= y < NAV_Y - 24):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if not (0 <= di < len(self._tracks)):
            return False
        self._sel = di
        t = self._tracks[di]
        from musi.player.screens.context_menu import ContextMenuScreen
        self.app.push(ContextMenuScreen(self.app, t["title"], [
            ("Play now",     lambda: self._play_from(di)),
            ("Play next",    lambda: self._queue([t["path"]], next_up=True)),
            ("Add to queue", lambda: self._queue([t["path"]], next_up=False)),
        ]))
        return True

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.DOWN:
            self._sel = min(len(self._tracks) - 1, self._sel + 1)
            self._clamp_scroll()
        elif button == Button.SELECT:
            if self._tracks:
                self._play_from(self._sel)
        elif button == Button.PLAY_PAUSE:
            self._play_album(shuffle=False)
        elif button == Button.BACK:
            self.app.pop()

    # ── actions ───────────────────────────────────────────────────────────────

    def _paths(self) -> list[str]:
        return [t["path"] for t in self._tracks]

    def _play_album(self, *, shuffle: bool) -> None:
        paths = self._paths()
        if not paths:
            return
        self.app.mpd.set_shuffle(shuffle)
        start = random.randrange(len(paths)) if shuffle else 0
        self.app.mpd.play_paths(paths, start_index=start)
        self.app.request_poll()
        self._open_now_playing()

    def _play_from(self, idx: int) -> None:
        self.app.mpd.play_paths(self._paths(), start_index=idx)
        self.app.request_poll()
        self._open_now_playing()

    def _queue(self, paths: list[str], next_up: bool) -> None:
        if next_up:
            self.app.mpd.queue_next(paths)
        else:
            self.app.mpd.queue_add(paths)
        self.app.request_poll()

    def _open_now_playing(self) -> None:
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))


def _draw_shuffle(surface, cx, cy, col) -> None:
    pygame.draw.line(surface, col, (cx - 11, cy - 5), (cx + 5, cy + 5), 2)
    pygame.draw.line(surface, col, (cx - 11, cy + 5), (cx + 5, cy - 5), 2)
    for dy in (-5, 5):
        pygame.draw.polygon(surface, col,
                            [(cx + 5, cy + dy - 3), (cx + 5, cy + dy + 3),
                             (cx + 11, cy + dy)])
