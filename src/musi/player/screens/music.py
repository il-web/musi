"""Music app host — Home / Library / Search over the merged dock.

Draws the dock and forwards everything else to the active child. Children are
built lazily and kept, so returning to a tab restores its scroll position.

Search keeps the nav row and loses only the now-playing strip: its keyboard
docks over the strip's pixels, but hiding the nav too would leave no way off
the tab.
"""
from __future__ import annotations

import pygame

from musi.player import backdrop, dock
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

CONTENT_Y = 26
CONTENT_BOTTOM = dock.DOCK_Y      # 406
SEARCH_TAB = 2


class MusicHostScreen(Screen):

    def __init__(self, app, tab: int = 0) -> None:
        super().__init__(app)
        self.tab = tab
        self._children: dict[int, Screen] = {}

    # ── children ──────────────────────────────────────────────────────────────

    @property
    def child(self) -> Screen:
        if self.tab not in self._children:
            self._children[self.tab] = self._build(self.tab)
        return self._children[self.tab]

    def _build(self, tab: int) -> Screen:
        if tab == 0:
            from musi.player.screens.home import HomeScreen
            return HomeScreen(self.app, list_y=CONTENT_Y, nav_y=CONTENT_BOTTOM)
        if tab == 1:
            from musi.player.screens.library import LibraryScreen
            return LibraryScreen(self.app, nav_y=CONTENT_BOTTOM)
        from musi.player.screens.search import SearchScreen
        return SearchScreen(self.app, top_y=CONTENT_Y)

    def set_tab(self, i: int) -> None:
        if i == self.tab or not (0 <= i < len(dock.TABS)):
            return
        self.child.on_exit()
        self.tab = i
        self.child.on_enter()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self.child.on_enter()

    def on_exit(self) -> None:
        self.child.on_exit()

    @property
    def animates(self) -> bool:
        return self.child.animates

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        self.child.draw(surface, status)
        # for_track is guarded, so this costs a dict lookup, not a query — and
        # the child already warmed it for the same track this frame.
        _bg, accent = backdrop.for_track(self.app.db, status)
        dock.draw(surface, self.app, status, active=self.tab,
                  accent=accent, strip=(self.tab != SEARCH_TAB))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = dock.hit(x, y)
        if zone:
            kind, index = zone
            if kind == "tab":
                self.set_tab(index)
                return None
            if self.tab != SEARCH_TAB and kind == "toggle":
                self.app.toggle_play()
                return None
            if self.tab != SEARCH_TAB and kind == "open":
                from musi.player.screens.now_playing import NowPlayingScreen
                self.app.push(NowPlayingScreen(self.app))
                return None
        return self.child.handle_touch(x, y)

    def handle_event(self, event) -> bool:
        return self.child.handle_event(event)

    def handle_scroll(self, dy: float) -> None:
        self.child.handle_scroll(dy)

    def handle_scroll_start(self) -> None:
        self.child.handle_scroll_start()

    def handle_scroll_end(self) -> None:
        self.child.handle_scroll_end()

    def handle_long_press(self, x: int, y: int) -> bool:
        return self.child.handle_long_press(x, y)

    def on_press(self, x: int, y: int) -> bool:
        return self.child.on_press(x, y)

    def on_drag(self, x: int, y: int) -> None:
        self.child.on_drag(x, y)

    def on_release(self, x: int, y: int) -> None:
        self.child.on_release(x, y)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        self.child.handle(button, status)
