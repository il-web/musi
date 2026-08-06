"""Music app — a tab host over the existing browse / search / history screens.

Draws the tab strip and the mini bar; everything else is forwarded to the
active child. Children are built lazily and kept, so returning to a tab
restores its scroll position.

The Search tab is the one tab without a mini bar: its keyboard docks at y 316
and runs to the bottom edge.
"""
from __future__ import annotations

import pygame

from musi.player import icons, minibar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

TAB_Y          = 26
TAB_H          = 32
CONTENT_Y      = TAB_Y + TAB_H          # 58
CONTENT_BOTTOM = minibar.BAR_Y          # 436
_TAB_W         = 80                     # 4 tabs across 320px
_SEARCH_TAB    = 1


class MusicScreen(Screen):

    TABS = ["Browse", "Search", "Recent", "Most"]

    def __init__(self, app, tab: int = 0) -> None:
        super().__init__(app)
        self.tab = tab
        self._children: dict[int, Screen] = {}
        self._tab_surfs: list[pygame.Surface] = []
        self._tab_surfs_on: list[pygame.Surface] = []
        self._crumb_surf: pygame.Surface | None = None
        self._crumb_text: str = ""

    # ── children ──────────────────────────────────────────────────────────────

    @property
    def child(self) -> Screen:
        if self.tab not in self._children:
            self._children[self.tab] = self._build(self.tab)
        return self._children[self.tab]

    def _build(self, tab: int) -> Screen:
        if tab == 0:
            from musi.player.screens.browse import BrowseScreen
            return BrowseScreen(self.app, list_y=CONTENT_Y, nav_y=CONTENT_BOTTOM)
        if tab == 1:
            from musi.player.screens.search import SearchScreen
            return SearchScreen(self.app, top_y=CONTENT_Y)
        from musi.player.screens.history import HistoryScreen
        mode = "recent" if tab == 2 else "most"
        return HistoryScreen(self.app, mode,
                             list_y=CONTENT_Y, nav_y=CONTENT_BOTTOM)

    def set_tab(self, i: int) -> None:
        if i == self.tab or not (0 <= i < len(self.TABS)):
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
        if not self._tab_surfs:
            self._tab_surfs    = [theme.render(t, 12, theme.DIM) for t in self.TABS]
            self._tab_surfs_on = [theme.render(t, 12, theme.BG, bold=True)
                                  for t in self.TABS]

        self.child.draw(surface, status)
        crumb = self._crumb()
        if crumb is None:
            self._draw_tabs(surface)
        else:
            self._draw_crumb(surface, crumb)
        if self.tab != _SEARCH_TAB:
            minibar.draw(surface, self.app, status)

    def _crumb(self) -> "str | None":
        """The child's breadcrumb when it has drilled in, else None.

        Children that never drill in (search, history) simply lack the
        attribute and always get the tab strip.
        """
        return getattr(self.child, "crumb", None)

    def _draw_crumb(self, surface: pygame.Surface, crumb: str) -> None:
        """Header band: a back chevron and where you are, instead of tabs."""
        pygame.draw.rect(surface, theme.BG, (0, TAB_Y, 320, TAB_H))
        cy = TAB_Y + TAB_H // 2
        icons.draw_chevron_left(surface, 16, cy, theme.ACCENT)
        if crumb != self._crumb_text:
            self._crumb_text = crumb
            self._crumb_surf = theme.render(crumb, 14, theme.WHITE, bold=True,
                                            max_width=272)
        surface.blit(self._crumb_surf,
                     self._crumb_surf.get_rect(x=30, centery=cy))

    def _draw_tabs(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, theme.BG, (0, TAB_Y, 320, TAB_H))
        for i, label in enumerate(self.TABS):
            rect = pygame.Rect(i * _TAB_W + 4, TAB_Y + 4, _TAB_W - 8, TAB_H - 8)
            if i == self.tab:
                pygame.draw.rect(surface, theme.ACCENT, rect, border_radius=6)
                surf = self._tab_surfs_on[i]
            else:
                surf = self._tab_surfs[i]
            surface.blit(surf, surf.get_rect(center=rect.center))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if TAB_Y <= y < CONTENT_Y:
            if self._crumb() is None:
                self.set_tab(min(len(self.TABS) - 1, x // _TAB_W))
            else:
                self.child.go_up()      # the band is a back row right now
            return None
        if self.tab != _SEARCH_TAB:
            zone = minibar.hit(x, y)
            if zone == "toggle":
                self.app.toggle_play()
                return None
            if zone == "open":
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
