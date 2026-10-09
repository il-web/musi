"""Settings screen — top-level settings menu."""
from __future__ import annotations

import pygame

from musi.player import audio_detect, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

MENU   = ["Bluetooth", "WiFi", "Playback", "Music Server", "Artwork", "API",
          "Updates", "Power"]

# Distribute the menu items evenly between the header and the mini bar so the
# menu fills the panel instead of bunching at the top.
_TOP    = 64
_BOTTOM = minibar.BAR_Y
_SLOT   = (_BOTTOM - _TOP) // len(MENU)   # vertical space per item
ITEM_H  = min(70, _SLOT)                  # card height (shrinks as MENU grows)


def _item_y(i: int) -> int:
    """Top y of item i, centred within its evenly-spaced slot."""
    return _TOP + i * _SLOT + (_SLOT - ITEM_H) // 2


class SettingsScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._sel = 0
        self._tap = PendingTap()
        self._header_surf: pygame.Surface | None = None
        self._menu_surfs:  list[pygame.Surface]  = []

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header_surf is None:
            self._header_surf = theme.render("Settings", 16, theme.WHITE, bold=True)
            self._menu_surfs  = [theme.render(m, 16, theme.WHITE) for m in MENU]

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_home=len(self.app.stack) > 1)
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

        minibar.draw(surface, self.app, status)

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
        name = MENU[self._sel]
        if name == "Bluetooth":
            from musi.player.screens.bluetooth import BluetoothScreen as cls
        elif name == "WiFi":
            from musi.player.screens.wifi import WifiScreen as cls
        elif name == "Playback":
            from musi.player.screens.playback import PlaybackScreen as cls
        elif name == "Music Server":
            from musi.player.screens.music_server import MusicServerScreen as cls
        elif name == "Artwork":
            from musi.player.screens.artwork import ArtworkScreen as cls
        elif name == "API":
            from musi.player.screens.api_settings import ApiSettingsScreen as cls
        elif name == "Updates":
            from musi.player.screens.updates import UpdatesScreen as cls
        else:
            from musi.player.screens.power import PowerScreen as cls
        self.app.push(cls(self.app))


# ── icon helpers ──────────────────────────────────────────────────────────────

def _draw_icon(surface, index, cx, cy, col):
    import math
    name = MENU[index]
    if name == "Bluetooth":
        pygame.draw.line(surface, col, (cx,     cy - 7), (cx,     cy + 7), 2)
        pygame.draw.line(surface, col, (cx,     cy - 7), (cx + 5, cy - 3), 2)
        pygame.draw.line(surface, col, (cx + 5, cy - 3), (cx,     cy    ), 2)
        pygame.draw.line(surface, col, (cx,     cy    ), (cx + 5, cy + 3), 2)
        pygame.draw.line(surface, col, (cx + 5, cy + 3), (cx,     cy + 7), 2)
    elif name == "WiFi":  # arcs
        for r in (8, 5, 2):
            if r == 2:
                pygame.draw.circle(surface, col, (cx, cy + 3), 2)
            else:
                pts = [(cx + int(r * math.cos(math.pi * (0.5 + 0.45 * t / 10))),
                        cy + 3 - int(r * math.sin(math.pi * (0.5 + 0.45 * t / 10))))
                       for t in range(-10, 11)]
                pygame.draw.lines(surface, col, False, pts, 2)
    elif name == "Playback":  # two crossing arcs, one fading into the other
        pygame.draw.arc(surface, col, pygame.Rect(cx - 9, cy - 7, 12, 14),
                        4.2, 5.9, 2)
        pygame.draw.arc(surface, col, pygame.Rect(cx - 3, cy - 7, 12, 14),
                        0.4, 2.1, 2)
    elif name == "Music Server":
        icons.draw_cloud(surface, cx, cy, col)
    elif name == "Artwork":  # picture frame with a peak and a sun
        pygame.draw.rect(surface, col, pygame.Rect(cx - 8, cy - 7, 16, 14), 2)
        pygame.draw.circle(surface, col, (cx + 3, cy - 3), 2)
        pygame.draw.lines(surface, col, False,
                          [(cx - 7, cy + 5), (cx - 2, cy - 1), (cx + 7, cy + 6)], 2)
    elif name == "API":  # globe (circle + equator + meridian)
        pygame.draw.circle(surface, col, (cx, cy), 8, 2)
        pygame.draw.line(surface, col, (cx - 7, cy), (cx + 7, cy), 2)
        pygame.draw.ellipse(surface, col, pygame.Rect(cx - 4, cy - 8, 8, 16), 2)
    elif name == "Updates":  # download arrow into a tray
        pygame.draw.line(surface, col, (cx, cy - 8), (cx, cy + 2), 2)
        pygame.draw.lines(surface, col, False,
                          [(cx - 4, cy - 2), (cx, cy + 2), (cx + 4, cy - 2)], 2)
        pygame.draw.line(surface, col, (cx - 6, cy + 6), (cx + 6, cy + 6), 2)
    elif name == "Power":  # power symbol (circle with top gap + stem)
        pygame.draw.arc(surface, col, pygame.Rect(cx - 8, cy - 7, 16, 16),
                        2.6, 0.55, 2)
        pygame.draw.line(surface, col, (cx, cy - 9), (cx, cy - 1), 2)



