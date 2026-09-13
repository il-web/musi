"""Playlist screen — one stored playlist: play, shuffle, reorder, remove.

Header + Play/Shuffle buttons mirror the Album screen; the track list borrows
the Queue screen's drag-handle reordering.
"""
from __future__ import annotations

import random

import pygame

from musi.player import audio_detect, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import FAVORITES, PlayerStatus

ITEM_H = 50
LIST_Y = 138
NAV_Y  = minibar.BAR_Y

PLAY_RECT    = pygame.Rect(24, 84, 176, 42)
SHUFFLE_RECT = pygame.Rect(208, 84, 88, 42)

HANDLE_X    = 292
HANDLE_ZONE = 262            # x >= this → drag handle; x < this → tap the row


def _fmt_total(seconds: float) -> str:
    m = int(seconds // 60)
    if m >= 60:
        return f"{m // 60} hr {m % 60} min"
    return f"{m} min" if m else "<1 min"


class PlaylistScreen(ListScreen):

    def __init__(self, app, name: str) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=NAV_Y)
        self._name = name
        self._tracks: list[dict] = []
        self._meta_line = ""

        # drag-reorder state (mirrors queue.py)
        self._drag_idx:  int | None = None
        self._drag_orig: int = 0
        self._drag_y:    int = 0

        self._title_surf: pygame.Surface | None = None
        self._meta_surf:  pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._refresh(reset=True)

    def _refresh(self, reset: bool = False) -> None:
        self._tracks = self.app.mpd.playlist_tracks(self._name)
        n = len(self._tracks)
        total = sum(t.get("duration", 0) or 0 for t in self._tracks)
        self._meta_line = f"{n} song{'s' if n != 1 else ''} · {_fmt_total(total)}"
        self._meta_surf = None
        self._klist.set_count(n, reset=reset)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._title_surf is None:
            self._title_surf = theme.render(self._name, 18, theme.WHITE,
                                            bold=True, max_width=272)
        if self._meta_surf is None:
            self._meta_surf = theme.render(self._meta_line, 11, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)

        tx = 14
        if self._name == FAVORITES:
            icons.draw_heart(surface, 20, 40, theme.ACCENT, filled=True)
            tx = 36
        surface.blit(self._title_surf, (tx, 30))
        surface.blit(self._meta_surf, (tx, 56))

        # Play / Shuffle
        pygame.draw.rect(surface, theme.ACCENT, PLAY_RECT, border_radius=21)
        icons.draw_play(surface, PLAY_RECT.x + 30, PLAY_RECT.centery, theme.WHITE)
        play_s = theme.render("Play", 13, theme.WHITE, bold=True)
        surface.blit(play_s, play_s.get_rect(x=PLAY_RECT.x + 46,
                                             centery=PLAY_RECT.centery))
        pygame.draw.rect(surface, theme.CARD_BG, SHUFFLE_RECT, border_radius=21)
        pygame.draw.rect(surface, theme.ACCENT, SHUFFLE_RECT, 1, border_radius=21)
        _draw_shuffle(surface, SHUFFLE_RECT.centerx, SHUFFLE_RECT.centery,
                      theme.ACCENT)

        if not self._tracks:
            msg = theme.render("This playlist is empty", 12, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=LIST_Y + 40))
        else:
            self.draw_list_viewport(surface, len(self._tracks))
            if self._drag_idx is not None:
                y = max(LIST_Y, min(NAV_Y - ITEM_H, self._drag_y - ITEM_H // 2))
                self._draw_row(surface, y, self._drag_idx, lifted=True)

        minibar.draw(surface, self.app, status)

    def _draw_row(self, surface: pygame.Surface, y: int, di: int,
                  lifted: bool = False) -> None:
        if di == self._drag_idx and not lifted:
            return
        t   = self._tracks[di]
        rect = pygame.Rect(8, y + 2, 304, ITEM_H - 6)
        pygame.draw.rect(surface, theme.ACCENT if lifted else theme.CARD_BG,
                         rect, border_radius=7)

        title = theme.render(t["title"], 13, theme.WHITE, bold=lifted,
                             max_width=232)
        surface.blit(title, (16, y + 8))
        if t.get("artist"):
            sub = theme.render(t["artist"], 10,
                               theme.WHITE if lifted else theme.DIM, max_width=232)
            surface.blit(sub, (16, y + 28))
        _handle(surface, HANDLE_X, y + ITEM_H // 2,
                theme.WHITE if lifted else theme.DIM)

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
            self._play(shuffle=False)
            return None
        if SHUFFLE_RECT.collidepoint(x, y):
            self._play(shuffle=True)
            return None
        if LIST_Y <= y < NAV_Y and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self._tracks):
                self._sel = di
                self._tap.set(lambda: self._play_from(di))
        return super().handle_touch(x, y)

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (LIST_Y <= y < NAV_Y):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if not (0 <= di < len(self._tracks)):
            return False
        self._sel = di
        t = self._tracks[di]
        from musi.player.screens.context_menu import ContextMenuScreen
        self.app.push(ContextMenuScreen(self.app, t["title"], [
            ("Play now",             lambda: self._play_from(di)),
            ("Play next",            lambda: self._queue([t["path"]], True)),
            ("Add to queue",         lambda: self._queue([t["path"]], False)),
            ("Remove from playlist", lambda: self._remove(di)),
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
            self._play(shuffle=False)
        elif button == Button.BACK:
            self.app.pop()

    # ── drag-reorder (handle column only) ────────────────────────────────────

    def on_press(self, x: int, y: int) -> bool:
        if x < HANDLE_ZONE or not (LIST_Y <= y < NAV_Y):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if 0 <= di < len(self._tracks):
            self._drag_idx  = di
            self._drag_orig = di
            self._drag_y    = y
            return True
        return False

    def on_drag(self, x: int, y: int) -> None:
        if self._drag_idx is None:
            return
        self._drag_y = y
        target = max(0, min(len(self._tracks) - 1,
                            self._klist.index_at(y - LIST_Y)))
        if target != self._drag_idx:
            it = self._tracks.pop(self._drag_idx)
            self._tracks.insert(target, it)
            self._drag_idx = target

    def on_release(self, x: int, y: int) -> None:
        if self._drag_idx is None:
            return
        final = self._drag_idx
        self._drag_idx = None
        if final != self._drag_orig:
            self.app.mpd.playlist_move(self._name, self._drag_orig, final)
        self._refresh()

    # ── actions ───────────────────────────────────────────────────────────────

    def _paths(self) -> list[str]:
        return [t["path"] for t in self._tracks if t["path"]]

    def _play(self, *, shuffle: bool) -> None:
        paths = self._paths()
        if not paths:
            return
        self.app.mpd.set_shuffle(shuffle)
        start = random.randrange(len(paths)) if shuffle else 0
        self.app.mpd.play_paths(paths, start_index=start)
        self.app.request_poll()
        self._open_now_playing()

    def _play_from(self, idx: int) -> None:
        paths = self._paths()
        if not paths:
            return
        self.app.mpd.play_paths(paths, start_index=min(idx, len(paths) - 1))
        self.app.request_poll()
        self._open_now_playing()

    def _queue(self, paths: list[str], next_up: bool) -> None:
        if next_up:
            self.app.mpd.queue_next(paths)
        else:
            self.app.mpd.queue_add(paths)
        self.app.request_poll()

    def _remove(self, pos: int) -> None:
        self.app.mpd.playlist_remove_at(self._name, pos)
        self._refresh()

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


def _handle(surface, cx, cy, col) -> None:
    for dy in (-5, 0, 5):
        pygame.draw.line(surface, col, (cx - 7, cy + dy), (cx + 7, cy + dy), 2)
