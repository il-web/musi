"""Artist page — one artist: play everything, your top songs, every album.

Opened from Library → Artists, and from Now Playing by tapping the artist's
name. The header sits on the blurred backdrop of the artist's newest album
(the same backdrop Now Playing uses), with that album's cover beside the name.
Rows below: "Top songs" (your most played, when there's history) and
"Albums" (newest first) — a tap opens the album.

All queries run in on_enter (album_queries.py); draw does no SQL.
"""
from __future__ import annotations

import random

import pygame

from musi.player import album_queries, art_cache, audio_detect, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus

HERO_Y, HERO_H = 26, 128
COVER = pygame.Rect(14, 44, 88, 88)
PLAY_RECT    = pygame.Rect(14, 162, 196, 40)
SHUFFLE_RECT = pygame.Rect(218, 162, 88, 40)
LIST_Y = 212
ITEM_H = 54
THUMB = 42


def _fmt_count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class ArtistScreen(ListScreen):

    def __init__(self, app, artist_id: int) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=minibar.BAR_Y)
        self.artist_id = artist_id
        self.name = ""
        self.rows: list[tuple] = []     # ("header", text) | ("song", row, i) | ("album", row)
        self._top: list = []
        self._tracks: list = []
        self._hero: pygame.Surface | None = None
        self._cover: pygame.Surface | None = None
        self._accent = theme.ACCENT
        self._stats = ""
        self._text: dict[str, pygame.Surface] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        db = self.app.db
        row = db.execute("SELECT name FROM artists WHERE id = ?",
                         (self.artist_id,)).fetchone()
        self.name = row[0] if row else "Unknown artist"
        albums = album_queries.artist_albums(db, self.artist_id)
        self._tracks = album_queries.artist_tracks(db, self.artist_id)
        self._top = album_queries.artist_top_tracks(db, self.artist_id)

        self.rows = []
        if self._top:
            self.rows.append(("header", "Top songs"))
            self.rows += [("song", t, i) for i, t in enumerate(self._top)]
        if albums:
            self.rows.append(("header", "Albums"))
            self.rows += [("album", a) for a in albums]
        self._klist.set_count(len(self.rows), reset=True)
        self._sel = next((i for i, r in enumerate(self.rows) if r[0] != "header"), 0)

        self._stats = " · ".join([_fmt_count(len(albums), "album"),
                                  _fmt_count(len(self._tracks), "song")])
        newest = albums[0] if albums else None
        self._hero = self._cover = None
        if newest is not None:
            if newest["backdrop_path"]:
                self._hero = art_cache.load_surface(newest["backdrop_path"], (320, 480))
            self._cover = art_cache.load_surface(newest["art_path"] or "", COVER.size)
            self._accent = art_cache.parse_palette(newest["palette"] or "", do_brighten=True)
        self._text = {}

    # ── draw ──────────────────────────────────────────────────────────────────

    def _t(self, key: str, text: str, size: int, col, bold=False, w=None) -> pygame.Surface:
        if key not in self._text:
            self._text[key] = theme.render(text, size, col, bold=bold, max_width=w or 0)
        return self._text[key]

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        surface.fill(theme.BG)

        # hero: the newest album's blurred backdrop, its cover, the name
        hero = pygame.Rect(0, HERO_Y, 320, HERO_H)
        if self._hero is not None:
            surface.blit(self._hero, hero.topleft, area=pygame.Rect(0, 150, 320, HERO_H))
        else:
            pygame.draw.rect(surface, theme.CARD_BG, hero)
        if self._cover is not None:
            surface.blit(self._cover, COVER.topleft)
        else:
            pygame.draw.rect(surface, (40, 40, 55), COVER, border_radius=6)
            icons.draw_music_note(surface, COVER.centerx, COVER.centery, (90, 90, 110))

        lines = theme.wrap(self.name, 19, True, 190)[:2]
        y = COVER.y + 2 if len(lines) > 1 else COVER.y + 14
        for i, line in enumerate(lines):
            s = self._t(f"name{i}", line, 19, theme.WHITE, bold=True, w=190)
            surface.blit(s, (COVER.right + 14, y))
            y += s.get_height() + 2
        st = self._t("stats", self._stats, 11, (200, 200, 212), w=190)
        surface.blit(st, (COVER.right + 14, y + 4))

        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)

        # play / shuffle everything by them
        live = bool(self._tracks)
        pygame.draw.rect(surface, self._accent if live else theme.CARD_BG,
                         PLAY_RECT, border_radius=20)
        fg = theme.text_on(self._accent) if live else theme.DIM
        icons.draw_play(surface, PLAY_RECT.x + 62, PLAY_RECT.centery, fg)
        p = theme.render_cached("Play", 13, fg, bold=True)
        surface.blit(p, p.get_rect(x=PLAY_RECT.x + 78, centery=PLAY_RECT.centery))
        pygame.draw.rect(surface, theme.CARD_BG, SHUFFLE_RECT, border_radius=20)
        pygame.draw.rect(surface, self._accent if live else theme.DIM,
                         SHUFFLE_RECT, 1, border_radius=20)
        from musi.player.screens.album import _draw_shuffle
        _draw_shuffle(surface, SHUFFLE_RECT.centerx, SHUFFLE_RECT.centery,
                      self._accent if live else theme.DIM)

        if self.rows:
            self.draw_list_viewport(surface, len(self.rows))
        else:
            m = self._t("empty", "Nothing by this artist yet", 12, theme.DIM)
            surface.blit(m, m.get_rect(centerx=160, y=LIST_Y + 40))
        minibar.draw(surface, self.app, status)

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        kind = self.rows[di][0]
        if kind == "header":
            h = self._t(f"h{di}", self.rows[di][1], 12, theme.DIM, bold=True)
            surface.blit(h, (14, y + ITEM_H - h.get_height() - 8))
            return
        sel = di == self._sel and self._tap.pending
        rect = pygame.Rect(8, y + 2, 304, ITEM_H - 4)
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG, rect,
                         border_radius=8)
        sub_col = theme.WHITE if sel else theme.DIM
        if kind == "song":
            t, i = self.rows[di][1], self.rows[di][2]
            n = self._t(f"n{i}", str(i + 1), 13, sub_col, bold=True)
            surface.blit(n, n.get_rect(centerx=30, centery=rect.centery))
            surface.blit(theme.render_cached(t["title"] or "?", 13, theme.WHITE, bold=sel,
                                      max_width=250), (52, y + 10))
            plays = t["plays"]
            sub = f"{t['album']} · {plays} play{'s' if plays != 1 else ''}"
            surface.blit(theme.render_cached(sub, 10, sub_col, max_width=250), (52, y + 30))
            return
        a = self.rows[di][1]                                  # an album
        thumb = art_cache.load_art_thumbnail(a["art_path"] or "", THUMB)
        tx, ty = 16, y + (ITEM_H - THUMB) // 2
        if thumb is not None:
            surface.blit(thumb, (tx, ty))
        else:
            pygame.draw.rect(surface, (40, 40, 55), (tx, ty, THUMB, THUMB), border_radius=4)
        surface.blit(theme.render_cached(a["title"], 13, theme.WHITE, bold=sel, max_width=220),
                     (68, y + 10))
        bits = [str(a["year"])] if a["year"] else []
        bits.append(_fmt_count(a["songs"], "song"))
        surface.blit(theme.render_cached(" · ".join(bits), 10, sub_col, max_width=220), (68, y + 30))
        icons.draw_chevron_right(surface, rect.right - 14, rect.centery, sub_col)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            self._open_now_playing()
            return None
        if PLAY_RECT.collidepoint(x, y):
            self.play(shuffle=False)
            return None
        if SHUFFLE_RECT.collidepoint(x, y):
            self.play(shuffle=True)
            return None
        if LIST_Y <= y < minibar.BAR_Y and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self.rows) and self.rows[di][0] != "header":
                self._sel = di
                self._tap.set(lambda di=di: self._open(di))
                return None
        return super().handle_touch(x, y)

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (LIST_Y <= y < minibar.BAR_Y):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if not (0 <= di < len(self.rows)) or self.rows[di][0] != "song":
            return False
        t = self.rows[di][1]
        from musi.player.screens.context_menu import ContextMenuScreen
        from musi.player.screens.playlist_picker import AddToPlaylistScreen
        self.app.push(ContextMenuScreen(self.app, t["title"], [
            ("Play now",         lambda: self._open(di)),
            ("Play next",        lambda: self._queue([t["path"]], True)),
            ("Add to queue",     lambda: self._queue([t["path"]], False)),
            ("Add to playlist…", lambda: self.app.push(
                AddToPlaylistScreen(self.app, [t["path"]]))),
        ]))
        return True

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._step(-1)
        elif button == Button.DOWN:
            self._step(1)
        elif button == Button.SELECT and 0 <= self._sel < len(self.rows):
            self._open(self._sel)
        elif button == Button.PLAY_PAUSE:
            self.play(shuffle=False)
        else:
            super().handle(button, status)

    def _step(self, d: int) -> None:
        i = self._sel + d
        while 0 <= i < len(self.rows) and self.rows[i][0] == "header":
            i += d
        if 0 <= i < len(self.rows):
            self._sel = i
            self._clamp_scroll()

    # ── actions ───────────────────────────────────────────────────────────────

    def _open(self, di: int) -> None:
        kind = self.rows[di][0]
        if kind == "album":
            from musi.player.screens.album import AlbumScreen
            self.app.push(AlbumScreen(self.app, self.rows[di][1]["id"]))
        elif kind == "song":
            paths = [t["path"] for t in self._top]
            self.app.mpd.play_paths(paths, start_index=self.rows[di][2])
            self.app.request_poll()
            self._open_now_playing()

    def play(self, *, shuffle: bool) -> None:
        paths = [t["path"] for t in self._tracks]
        if not paths:
            return
        self.app.mpd.set_shuffle(shuffle)
        start = random.randrange(len(paths)) if shuffle else 0
        self.app.mpd.play_paths(paths, start_index=start)
        self.app.request_poll()
        self._open_now_playing()

    def _queue(self, paths: list[str], next_up: bool) -> None:
        (self.app.mpd.queue_next if next_up else self.app.mpd.queue_add)(paths)
        self.app.request_poll()

    def _open_now_playing(self) -> None:
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))
