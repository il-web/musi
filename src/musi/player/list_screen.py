"""Base class for screens containing a scrollable list."""

from __future__ import annotations

import pygame

from musi.player.screen import Screen
from musi.player.widgets import KineticList, PendingTap, draw_scrollbar


class ListScreen(Screen):
    """Base class for list-based screens."""

    def __init__(self, app, item_h: int, list_y: int, nav_y: int) -> None:
        super().__init__(app)
        self.item_h = item_h
        self.list_y = list_y
        self.nav_y = nav_y
        self.view_h = nav_y - list_y

        self._sel = 0
        self._klist = KineticList(item_h, self.view_h)
        self._tap = PendingTap()

    def handle_scroll(self, dy: float) -> None:
        self._klist.scroll_by(dy)

    def handle_scroll_start(self) -> None:
        self._klist.start_touch()

    def handle_scroll_end(self) -> None:
        self._klist.end_touch()

    def _clamp_scroll(self) -> None:
        self._klist.ensure_visible(self._sel)

    def draw_list_viewport(self, surface: pygame.Surface, num_items: int) -> None:
        """Draw the scrollable list viewport. Subclasses must implement _draw_row."""
        if num_items == 0:
            return

        self._klist.update()
        self._tap.update()
        first = self._klist.first_visible()
        shift = self._klist.pixel_shift()

        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, self.list_y, 320, self.view_h))

        for vi in range(self._klist.visible_rows()):
            di = first + vi
            if di >= num_items:
                break
            y = self.list_y + vi * self.item_h - shift
            self._draw_row(surface, y, di)

        surface.set_clip(clip)
        
        # draw_scrollbar is drawn unconditionally in BrowseScreen right after loop
        draw_scrollbar(surface, 314, self.list_y, self.view_h, self._klist)

    def _draw_row(self, surface: pygame.Surface, y: int, index: int) -> None:
        """Render a single row at the given absolute y coordinate. Must be overridden."""
        pass
