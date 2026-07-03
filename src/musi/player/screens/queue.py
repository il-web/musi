"""Queue screen — the up-next list, with tap-to-play and drag-to-reorder.

Reached from the Now Playing screen's Queue button. Tap a row to jump to that
track; drag the handle on the right to move a track up or down. Dragging
anywhere else scrolls the list.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus, QueueItem
from musi.player.screen import Screen
from musi.player.widgets import KineticList, PendingTap, draw_scrollbar

LIST_Y      = 58
ITEM_H      = 50
NAV_Y       = 462
MAX_VIS     = (NAV_Y - LIST_Y) // ITEM_H
HANDLE_X    = 286            # drag-handle centre
HANDLE_ZONE = 256            # x >= this → handle (drag); x < this → row body (tap)


class QueueScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._items: list[QueueItem] = []
        self._klist = KineticList(ITEM_H, NAV_Y - LIST_Y)
        self._tap   = PendingTap()
        # drag-reorder state
        self._drag_idx:  int | None = None   # current index of dragged row
        self._drag_orig: int = 0             # its original MPD position
        self._drag_y:    int = 0             # current finger y
        # static surfaces
        self._hdr:  pygame.Surface | None = None
        self._hint: pygame.Surface | None = None

    def on_enter(self) -> None:
        self._refresh(reset=True)

    def _refresh(self, reset: bool = False) -> None:
        self._items = self.app.mpd.queue()
        self._klist.set_count(len(self._items), reset=reset)

    # ── draw ────────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr  = theme.render("Queue", 16, theme.WHITE, bold=True)
            self._hint = theme.render("tap = play   ·   drag handle = reorder",
                                      10, theme.DIM, max_width=300)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._hdr, (14, 26))

        if not self._items:
            msg = theme.render("Queue is empty", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=220))
        else:
            self._klist.update()
            self._tap.update()
            first = self._klist.first_visible()
            shift = self._klist.pixel_shift()
            clip  = surface.get_clip()
            surface.set_clip(pygame.Rect(0, LIST_Y, 320, NAV_Y - LIST_Y))
            for vi in range(self._klist.visible_rows()):
                di = first + vi
                if di >= len(self._items):
                    break
                if di == self._drag_idx:
                    continue   # the dragged row is drawn floating, below
                self._draw_row(surface, LIST_Y + vi * ITEM_H - shift, di,
                               status, lifted=False)

            if self._drag_idx is not None:
                y = max(LIST_Y, min(NAV_Y - ITEM_H, self._drag_y - ITEM_H // 2))
                self._draw_row(surface, y, self._drag_idx, status, lifted=True)
            surface.set_clip(clip)

            draw_scrollbar(surface, 315, LIST_Y, NAV_Y - LIST_Y, self._klist)

        surface.blit(self._hint, self._hint.get_rect(centerx=160, y=NAV_Y + 2))

    def _draw_row(self, surface, y, di, status, lifted):
        item   = self._items[di]
        is_cur = (item.pos == status.queue_pos)

        rect = pygame.Rect(8, y + 2, 304, ITEM_H - 6)
        if lifted:
            bg = theme.ACCENT
        elif is_cur:
            bg = (38, 58, 48)
        else:
            bg = theme.CARD_BG
        pygame.draw.rect(surface, bg, rect, border_radius=7)

        if is_cur:
            _play_tri(surface, 22, y + ITEM_H // 2,
                      theme.WHITE if lifted else (120, 230, 140))
        tx = 38
        bold  = lifted or is_cur
        title = theme.render(item.title, 13, theme.WHITE, bold=bold, max_width=212)
        surface.blit(title, (tx, y + 8))
        if item.artist:
            sub = theme.render(item.artist, 10,
                               theme.WHITE if bold else theme.DIM, max_width=212)
            surface.blit(sub, (tx, y + 28))

        _handle(surface, HANDLE_X, y + ITEM_H // 2, theme.WHITE if lifted else theme.DIM)

    # ── input ────────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.BACK
        if LIST_Y <= y < NAV_Y and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self._items):
                pos = self._items[di].pos
                self._tap.set(lambda: (self.app.mpd.play_pos(pos),
                                       self.app.request_poll()))
        return None

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (LIST_Y <= y < NAV_Y):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if not (0 <= di < len(self._items)):
            return False
        item = self._items[di]
        from musi.player.screens.context_menu import ContextMenuScreen
        self.app.push(ContextMenuScreen(self.app, item.title, [
            ("Play",              lambda: self._menu_play(item.pos)),
            ("Remove from queue", lambda: self._menu_remove(item.pos)),
        ]))
        return True

    def _menu_play(self, pos: int) -> None:
        self.app.mpd.play_pos(pos)
        self.app.request_poll()

    def _menu_remove(self, pos: int) -> None:
        self.app.mpd.remove_pos(pos)
        self.app.request_poll()
        self._refresh()

    def handle_scroll(self, dy: float) -> None:
        self._klist.scroll_by(dy)

    def handle_scroll_start(self) -> None:
        self._klist.start_touch()

    def handle_scroll_end(self) -> None:
        self._klist.end_touch()

    # drag the handle to reorder
    def on_press(self, x: int, y: int) -> bool:
        if x < HANDLE_ZONE or not (LIST_Y <= y < NAV_Y):
            return False
        di = self._klist.index_at(y - LIST_Y)
        if 0 <= di < len(self._items):
            self._drag_idx  = di
            self._drag_orig = self._items[di].pos
            self._drag_y    = y
            return True
        return False

    def on_drag(self, x: int, y: int) -> None:
        if self._drag_idx is None:
            return
        self._drag_y = y
        target = max(0, min(len(self._items) - 1,
                            self._klist.index_at(y - LIST_Y)))
        if target != self._drag_idx:
            it = self._items.pop(self._drag_idx)
            self._items.insert(target, it)
            self._drag_idx = target

    def on_release(self, x: int, y: int) -> None:
        if self._drag_idx is None:
            return
        final = self._drag_idx
        self._drag_idx = None
        self.app.mpd.move(self._drag_orig, final)
        self._refresh()


# ── helpers ───────────────────────────────────────────────────────────────────

def _play_tri(surface, cx, cy, col):
    pygame.draw.polygon(surface, col, [(cx - 4, cy - 5), (cx - 4, cy + 5), (cx + 5, cy)])


def _handle(surface, cx, cy, col):
    for dy in (-5, 0, 5):
        pygame.draw.line(surface, col, (cx - 7, cy + dy), (cx + 7, cy + dy), 2)
