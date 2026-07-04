"""Settings screen — top-level settings menu."""
from __future__ import annotations

import pygame

from musi.player import audio_detect, icons, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

MENU   = ["Bluetooth", "WiFi", "Sleep Timer", "Updates", "Power"]
ITEM_H = 70          # card height
NAV_Y  = 456

# Distribute the menu items evenly between the header and the nav hint so the
# menu fills the panel instead of bunching at the top.
_TOP    = 64
_BOTTOM = 436
_SLOT   = (_BOTTOM - _TOP) // len(MENU)   # vertical space per item


def _item_y(i: int) -> int:
    """Top y of item i, centred within its evenly-spaced slot."""
    return _TOP + i * _SLOT + (_SLOT - ITEM_H) // 2


class SettingsScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._sel = 0
        self._tap = PendingTap()
        self._header_surf: pygame.Surface | None = None
        self._nav_surf:    pygame.Surface | None = None
        self._menu_surfs:  list[pygame.Surface]  = []

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header_surf is None:
            self._header_surf = theme.render("Settings", 16, theme.WHITE, bold=True)
            self._nav_surf    = theme.render("Enter = open   Esc = back", 10, theme.WHITE)
            self._menu_surfs  = [theme.render(m, 16, theme.WHITE) for m in MENU]

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)
        self._tap.update()

        # section header
        surface.blit(self._header_surf, (14, 26))

        # menu items
        for i, label_surf in enumerate(self._menu_surfs):
            y = _item_y(i)
            rect = pygame.Rect(10, y, 300, ITEM_H - 4)

            if i == self._sel:
                pygame.draw.rect(surface, theme.ACCENT, rect, border_radius=8)
                _draw_icon(surface, i, 36, y + (ITEM_H - 4) // 2, theme.WHITE)
                surface.blit(label_surf, (60, y + (ITEM_H - label_surf.get_height()) // 2 - 2))
                icons.draw_chevron_right(surface, 302, y + (ITEM_H - 4) // 2, theme.WHITE)
            else:
                pygame.draw.rect(surface, theme.CARD_BG, rect, border_radius=8)
                _draw_icon(surface, i, 36, y + (ITEM_H - 4) // 2, theme.DIM)
                dim = theme.render(MENU[i], 16, theme.DIM)
                surface.blit(dim, (60, y + (ITEM_H - dim.get_height()) // 2 - 2))
                icons.draw_chevron_right(surface, 302, y + (ITEM_H - 4) // 2, theme.CARD_BG)

            # live countdown on the Sleep Timer row
            if MENU[i] == "Sleep Timer":
                rem = self.app.sleep_remaining()
                if rem is not None:
                    rem_s = theme.render(f"{int(rem // 60) + 1} min", 12,
                                         theme.WHITE if i == self._sel else theme.DIM)
                    surface.blit(rem_s, (294 - rem_s.get_width(),
                                         y + (ITEM_H - rem_s.get_height()) // 2 - 2))

        surface.blit(self._nav_surf, self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if _TOP <= y < _BOTTOM and not self._tap.pending:
            i = (y - _TOP) // _SLOT
            if 0 <= i < len(MENU):
                self._sel = i
                self._tap.set(self._open)
                return None
        return super().handle_touch(x, y)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = (self._sel - 1) % len(MENU)
        elif button == Button.DOWN:
            self._sel = (self._sel + 1) % len(MENU)
        elif button == Button.SELECT:
            self._open()
        elif button == Button.BACK:
            self.app.pop()

    def _open(self) -> None:
        if self._sel == 0:
            from musi.player.screens.bluetooth import BluetoothScreen
            self.app.push(BluetoothScreen(self.app))
        elif self._sel == 1:
            from musi.player.screens.wifi import WifiScreen
            self.app.push(WifiScreen(self.app))
        elif self._sel == 2:
            self._open_sleep_menu()
        elif self._sel == 3:
            from musi.player.screens.updates import UpdatesScreen
            self.app.push(UpdatesScreen(self.app))
        elif self._sel == 4:
            from musi.player.screens.power import PowerScreen
            self.app.push(PowerScreen(self.app))

    def _open_sleep_menu(self) -> None:
        from musi.player.screens.context_menu import ContextMenuScreen

        def set_timer(minutes):
            return lambda: self.app.set_sleep_timer(minutes)

        self.app.push(ContextMenuScreen(self.app, "Sleep timer — pause after", [
            ("Off",        set_timer(None)),
            ("15 minutes", set_timer(15)),
            ("30 minutes", set_timer(30)),
            ("60 minutes", set_timer(60)),
            ("90 minutes", set_timer(90)),
        ]))


# ── icon helpers ──────────────────────────────────────────────────────────────

def _draw_icon(surface, index, cx, cy, col):
    import math
    if index == 0:   # Bluetooth
        pygame.draw.line(surface, col, (cx,     cy - 7), (cx,     cy + 7), 2)
        pygame.draw.line(surface, col, (cx,     cy - 7), (cx + 5, cy - 3), 2)
        pygame.draw.line(surface, col, (cx + 5, cy - 3), (cx,     cy    ), 2)
        pygame.draw.line(surface, col, (cx,     cy    ), (cx + 5, cy + 3), 2)
        pygame.draw.line(surface, col, (cx + 5, cy + 3), (cx,     cy + 7), 2)
    elif index == 1:  # WiFi — arcs
        for r in (8, 5, 2):
            if r == 2:
                pygame.draw.circle(surface, col, (cx, cy + 3), 2)
            else:
                pts = [(cx + int(r * math.cos(math.pi * (0.5 + 0.45 * t / 10))),
                        cy + 3 - int(r * math.sin(math.pi * (0.5 + 0.45 * t / 10))))
                       for t in range(-10, 11)]
                pygame.draw.lines(surface, col, False, pts, 2)
    elif index == 2:  # Sleep Timer — crescent moon
        outer = [(cx + 8 * math.cos(math.radians(d)),
                  cy + 8 * math.sin(math.radians(d))) for d in range(60, 301, 20)]
        inner = [(cx + 4 + 6 * math.cos(math.radians(d)),
                  cy + 6 * math.sin(math.radians(d))) for d in range(285, 74, -20)]
        pygame.draw.polygon(surface, col, outer + inner)
    elif index == 3:  # Updates — download arrow into a tray
        pygame.draw.line(surface, col, (cx, cy - 8), (cx, cy + 2), 2)
        pygame.draw.lines(surface, col, False,
                          [(cx - 4, cy - 2), (cx, cy + 2), (cx + 4, cy - 2)], 2)
        pygame.draw.line(surface, col, (cx - 6, cy + 6), (cx + 6, cy + 6), 2)
    elif index == 4:  # Power — power symbol (circle with top gap + stem)
        pygame.draw.arc(surface, col, pygame.Rect(cx - 8, cy - 7, 16, 16),
                        2.6, 0.55, 2)
        pygame.draw.line(surface, col, (cx, cy - 9), (cx, cy - 1), 2)



