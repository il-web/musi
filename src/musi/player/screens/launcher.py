"""Launcher — one large app tile per page, swiped horizontally.

The stack root. Captures every gesture via on_press (app.py:348) and resolves
tap-vs-swipe itself on release, so app.py's gesture plumbing is untouched.

Each page is rendered once to a cached Surface covering y 26..436; a drag frame
is two blits plus the mini bar. A page's surface is rebuilt only when its live
subtitle changes.
"""
from __future__ import annotations

import pygame

from musi.player import app_tiles, audio_detect, minibar, prefs, statusbar, theme, wallpaper
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import Carousel

PAGE_Y      = 26                    # top of the page area (below the status bar)
PAGE_BOTTOM = minibar.BAR_Y         # 436
PAGE_H      = PAGE_BOTTOM - PAGE_Y  # 410

TILE_Y   = 74      # tile top, relative to PAGE_Y
LABEL_Y  = 210     # app name top, relative to PAGE_Y
SUB_Y    = 238     # subtitle top, relative to PAGE_Y
DOTS_Y   = 366     # page dots centre, relative to PAGE_Y

# Scrim — the stock artwork is brightest mid-screen, exactly where the app name
# and subtitle sit. A stationary band keeps them legible without hiding the art.
# Relative to PAGE_Y, like the other layout constants here.
SCRIM_Y     = 190
SCRIM_H     = 84
SCRIM_ALPHA = 150

_SLOP = 12         # matches app.TAP_SLOP_PX — movement below this is a tap


class LauncherScreen(Screen):

    APPS: list[tuple[str, str]] = [
        ("music",    "Music"),
        ("settings", "Settings"),
        ("clock",    "Clock"),
        ("sleep",    "Sleep"),
    ]

    SCRIM_Y     = SCRIM_Y
    SCRIM_H     = SCRIM_H
    SCRIM_ALPHA = SCRIM_ALPHA

    def __init__(self, app) -> None:
        super().__init__(app)
        self._car = Carousel(len(self.APPS))
        self._pages: dict[int, pygame.Surface] = {}
        self._page_subs: dict[int, str] = {}
        self._press_x = 0
        self._last_x  = 0
        self._moved   = 0.0
        self._albums: int | None = None   # counted once, not once per frame
        self._scrim_surf: pygame.Surface | None = None

    @property
    def animates(self) -> bool:
        return self._car.animating

    def on_enter(self) -> None:
        """Recount the library — it may have grown while we were in an app."""
        self._albums = None

    # ── subtitles ─────────────────────────────────────────────────────────────

    def subtitle(self, key: str) -> str:
        if key == "music":
            if self._albums is None:
                self._albums = self.app.db.execute(
                    "SELECT COUNT(*) FROM albums").fetchone()[0]
            n = self._albums
            return f"{n} album" if n == 1 else f"{n} albums"
        if key == "clock":
            from datetime import datetime

            from musi.player.screens.clock import format_now
            return format_now(datetime.now())[0]
        if key == "sleep":
            from musi.player.screens.sleep import format_remaining
            return format_remaining(self.app.sleep_remaining())
        return ""

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        self._car.update()

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type())

        # Wallpaper goes on the main surface, not into the pages: a page is
        # blitted at a sliding x-offset, so artwork inside one would slide with
        # it. Both cached lookups — no disk access here.
        paper = wallpaper.surface(str(prefs.get("wallpaper")))
        if paper is not None:
            surface.blit(paper, (0, PAGE_Y))
            surface.blit(self._scrim(), (0, PAGE_Y + SCRIM_Y))

        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, PAGE_Y, 320, PAGE_H))
        for idx, dx in self._car.visible_pages():
            surface.blit(self._page(idx), (dx, PAGE_Y))
        surface.set_clip(clip)

        minibar.draw(surface, self.app, status)

    def _scrim(self) -> pygame.Surface:
        """Soft dark band behind the label, built once. Fades in and out so it
        reads as shading rather than a rectangle laid over the artwork."""
        if self._scrim_surf is None:
            s = pygame.Surface((320, SCRIM_H), pygame.SRCALPHA)
            half = SCRIM_H / 2
            for y in range(SCRIM_H):
                a = int(SCRIM_ALPHA * (1.0 - abs(y - half) / half))
                pygame.draw.line(s, (0, 0, 0, a), (0, y), (319, y))
            self._scrim_surf = s
        return self._scrim_surf

    def _page(self, idx: int) -> pygame.Surface:
        """Cached page surface; rebuilt when its live subtitle changes."""
        key, label = self.APPS[idx]
        sub = self.subtitle(key)
        if idx in self._pages and self._page_subs.get(idx) == sub:
            return self._pages[idx]

        # Transparent: the wallpaper is drawn underneath and must show through.
        # With no wallpaper set this composites over the theme.BG fill instead,
        # which looks identical to the old opaque page.
        page = pygame.Surface((320, PAGE_H), pygame.SRCALPHA)

        tile = app_tiles.render_tile(key)
        page.blit(tile, tile.get_rect(centerx=160, y=TILE_Y))

        name = theme.render(label, 18, theme.WHITE, bold=True)
        page.blit(name, name.get_rect(centerx=160, y=LABEL_Y))

        if sub:
            sub_s = theme.render(sub, 11, theme.DIM)
            page.blit(sub_s, sub_s.get_rect(centerx=160, y=SUB_Y))

        for i in range(len(self.APPS)):
            cx = 160 + (i - (len(self.APPS) - 1) / 2) * 14
            col = app_tiles.accent(key) if i == idx else (58, 58, 74)
            pygame.draw.circle(page, col, (int(cx), DOTS_Y), 3)

        self._pages[idx] = page
        self._page_subs[idx] = sub
        return page

    # ── gesture (captured: app.py routes drag/release straight here) ───────────

    def on_press(self, x: int, y: int) -> bool:
        self._press_x = self._last_x = x
        self._moved = 0.0
        self._car.start_touch()
        return True

    def on_drag(self, x: int, y: int) -> None:
        dx = x - self._last_x
        self._last_x = x
        self._moved += abs(dx)
        self._car.drag_by(dx)

    def on_release(self, x: int, y: int) -> None:
        if self._moved >= _SLOP:
            self._car.end_touch()
            return

        self._car.end_touch()               # settles back to centre
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
        elif zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
        elif PAGE_Y <= y < PAGE_BOTTOM:
            self._open(self._car.index)

    def _open(self, idx: int) -> None:
        key = self.APPS[idx][0]
        if key == "music":
            from musi.player.screens.music import MusicScreen
            self.app.push(MusicScreen(self.app))
        elif key == "settings":
            from musi.player.screens.settings import SettingsScreen
            self.app.push(SettingsScreen(self.app))
        elif key == "clock":
            from musi.player.screens.clock import ClockScreen
            self.app.push(ClockScreen(self.app))
        elif key == "sleep":
            from musi.player.screens.sleep import SleepScreen
            self.app.push(SleepScreen(self.app))

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.PLAY_PAUSE:
            self.app.toggle_play()
        elif button == Button.NEXT:
            self._open(self._car.index)
