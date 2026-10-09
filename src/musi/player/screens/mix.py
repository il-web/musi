"""One Smart Mix (or a song radio) — play, shuffle, or start from any track.

Read-only: a mix is rebuilt from your listening, so there is nothing to
reorder or delete. Layout follows the Playlist screen.
"""
from __future__ import annotations

import random
import threading

import pygame

from musi.library import mixes, remote
from musi.player import audio_detect, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus
from musi.player.screens.playlist import (ITEM_H, LIST_Y, NAV_Y, PLAY_RECT,
                                          SHUFFLE_RECT, _draw_shuffle)


class MixScreen(ListScreen):

    def __init__(self, app, mix: mixes.Mix) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=NAV_Y)
        self.mix = mix
        self._klist.set_count(len(mix.tracks), reset=True)
        self._title: pygame.Surface | None = None
        self._sub: pygame.Surface | None = None

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._title is None:
            self._title = theme.render(self.mix.title, 18, theme.WHITE, bold=True,
                                       max_width=248)
            n = len(self.mix.tracks)
            self._sub = theme.render(f"{self.mix.subtitle} · {n} song{'s' if n != 1 else ''}",
                                     11, theme.DIM, max_width=248)
        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)

        c0, c1 = self.mix.colours
        pygame.draw.rect(surface, c1, (14, 32, 38, 38), border_radius=8)
        pygame.draw.rect(surface, c0, (14, 32, 38, 19), border_top_left_radius=8,
                         border_top_right_radius=8)
        icons.draw_music_note(surface, 33, 52, theme.WHITE)
        surface.blit(self._title, (60, 30))
        surface.blit(self._sub, (60, 56))

        pygame.draw.rect(surface, theme.ACCENT, PLAY_RECT, border_radius=21)
        icons.draw_play(surface, PLAY_RECT.x + 30, PLAY_RECT.centery, theme.WHITE)
        p = theme.render("Play", 13, theme.WHITE, bold=True)
        surface.blit(p, p.get_rect(x=PLAY_RECT.x + 46, centery=PLAY_RECT.centery))
        pygame.draw.rect(surface, theme.CARD_BG, SHUFFLE_RECT, border_radius=21)
        pygame.draw.rect(surface, theme.ACCENT, SHUFFLE_RECT, 1, border_radius=21)
        _draw_shuffle(surface, SHUFFLE_RECT.centerx, SHUFFLE_RECT.centery, theme.ACCENT)

        self.draw_list_viewport(surface, len(self.mix.tracks))
        minibar.draw(surface, self.app, status)

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        t = self.mix.tracks[di]
        sel = di == self._sel and self._tap.pending
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG,
                         (8, y + 2, 304, ITEM_H - 6), border_radius=7)
        cloud = remote.is_server(t["path"])
        title = theme.render(t.get("title") or "?", 13, theme.WHITE, bold=sel,
                             max_width=272 - (icons.CLOUD_W if cloud else 0))
        r = surface.blit(title, (16, y + 8))
        if cloud:
            icons.draw_cloud_after(surface, r, theme.WHITE if sel else theme.DIM)
        if t.get("artist"):
            surface.blit(theme.render(t["artist"], 10, theme.WHITE if sel else theme.DIM,
                                      max_width=272), (16, y + 28))

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
        if LIST_Y <= y < NAV_Y and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self.mix.tracks):
                self._sel = di
                self._tap.set(lambda: self.play(start=di))
                return None
        return super().handle_touch(x, y)

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (LIST_Y <= y < NAV_Y):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if not (0 <= di < len(self.mix.tracks)):
            return False
        t = self.mix.tracks[di]
        from musi.player.screens.context_menu import ContextMenuScreen
        self.app.push(ContextMenuScreen(self.app, t.get("title", ""), [
            ("Play now",     lambda: self.play(start=di)),
            ("Play next",    lambda: self._queue(t["path"], True)),
            ("Add to queue", lambda: self._queue(t["path"], False)),
            ("Start radio",  lambda: start_radio(self.app, t)),
        ]))
        return True

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.SELECT:
            self.play(start=max(0, self._sel))
        else:
            super().handle(button, status)

    # ── actions ───────────────────────────────────────────────────────────────

    def play(self, *, shuffle: bool = False, start: int = 0) -> None:
        paths = [t["path"] for t in self.mix.tracks if t.get("path")]
        if not paths:
            return
        self.app.mpd.set_shuffle(shuffle)
        if shuffle:
            start = random.randrange(len(paths))
        self.app.mpd.play_paths(paths, start_index=min(start, len(paths) - 1))
        self.app.request_poll()
        self._open_now_playing()

    def _queue(self, path: str, next_up: bool) -> None:
        (self.app.mpd.queue_next if next_up else self.app.mpd.queue_add)([path])
        self.app.request_poll()

    def _open_now_playing(self) -> None:
        from musi.player.screens.now_playing import NowPlayingScreen
        self.app.push(NowPlayingScreen(self.app))


class _Radio(MixScreen):
    """Song radio: built on a worker (Navidrome is asked for similar songs),
    then plays straight away. Until then it shows 'Finding similar songs…'."""

    def __init__(self, app, seed: dict) -> None:
        super().__init__(app, mixes.Mix("radio", f"{seed.get('title', 'Song')} Radio",
                                        "Finding similar songs…", [seed]))
        self._ready: mixes.Mix | None = None
        self._busy = True

        def work() -> None:
            from musi.library import config, subsonic
            from musi.library.db import open_db
            conn = open_db(config.db_path())
            try:
                self._ready = mixes.song_radio(conn, seed, subsonic.Client.from_settings())
            except Exception:
                self._ready = mixes.Mix("radio", self.mix.title, "Couldn't build a radio", [seed])
            finally:
                conn.close()

        threading.Thread(target=work, daemon=True).start()

    @property
    def animates(self) -> bool:
        return self._busy

    def draw(self, surface, status) -> None:
        if self._busy and self._ready is not None:   # built: show it, then play
            self._busy = False
            self.mix = self._ready
            self._title = None
            self._klist.set_count(len(self.mix.tracks), reset=True)
            self.play()
            return
        super().draw(surface, status)


def start_radio(app, track: dict) -> None:
    """Long-press → 'Start radio' anywhere a track is listed."""
    app.push(_Radio(app, {"path": track.get("path", ""), "title": track.get("title", ""),
                          "artist": track.get("artist", ""),
                          "duration": track.get("duration") or 0}))
