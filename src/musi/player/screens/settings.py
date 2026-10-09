"""Settings — grouped like iOS: Sound, Connections, Library, System.

Each group is a heading over one rounded card of rows. The groups are taller
than the screen, so the list scrolls (drag), and the keyboard / D-pad
selection keeps the selected row in view.
"""
from __future__ import annotations

import pygame

from musi.player import audio_detect, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import PendingTap

GROUPS: list[tuple[str, list[str]]] = [
    ("Sound",       ["Playback", "Bluetooth"]),
    ("Connections", ["WiFi", "Music Server", "API"]),
    ("Library",     ["Artwork"]),
    ("System",      ["Updates", "Power"]),
]
MENU = [name for _, names in GROUPS for name in names]

_TOP     = 60                     # list area: below the header …
_BOTTOM  = minibar.BAR_Y          # … down to the mini bar
ROW_H    = 46
HEAD_H   = 28                     # group heading
GROUP_GAP = 10
CARD_X, CARD_W = 10, 300


def _layout() -> tuple[list[tuple[str, int]], list[int], int]:
    """(headings [(title, y)], row tops by MENU index, total height) —
    y measured from the top of the scrolling list."""
    heads, rows, y = [], [], 0
    for title, names in GROUPS:
        heads.append((title, y))
        y += HEAD_H
        for _ in names:
            rows.append(y)
            y += ROW_H
        y += GROUP_GAP
    return heads, rows, y


class SettingsScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._sel = 0
        self._tap = PendingTap()
        self._header_surf: pygame.Surface | None = None
        self._scroll = 0.0
        self._heads, self._rows, total = _layout()
        self._max_scroll = max(0.0, total - (_BOTTOM - _TOP))

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header_surf is None:
            self._header_surf = theme.render("Settings", 16, theme.WHITE, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        self._tap.update()
        surface.blit(self._header_surf, (14, 30))

        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(0, _TOP, 320, _BOTTOM - _TOP))
        top = _TOP - int(self._scroll)
        i = 0
        for gi, (title, names) in enumerate(GROUPS):
            head_y = top + self._heads[gi][1]
            h = theme.render_cached(title.upper(), 10, theme.DIM, bold=True)
            surface.blit(h, (CARD_X + 8, head_y + HEAD_H - h.get_height() - 6))
            card = pygame.Rect(CARD_X, top + self._rows[i], CARD_W, ROW_H * len(names))
            pygame.draw.rect(surface, theme.CARD_BG, card, border_radius=12)
            for k, name in enumerate(names):
                y = top + self._rows[i]
                sel = i == self._sel and self._tap.pending
                if sel:
                    r = pygame.Rect(CARD_X, y, CARD_W, ROW_H)
                    pygame.draw.rect(surface, theme.ACCENT, r, border_radius=12 if len(names) == 1 else 0)
                elif k:
                    pygame.draw.line(surface, (40, 40, 56), (CARD_X + 48, y),
                                     (CARD_X + CARD_W - 12, y), 1)
                col = theme.WHITE if sel else theme.DIM
                _draw_icon(surface, i, CARD_X + 26, y + ROW_H // 2, theme.WHITE if sel else theme.ACCENT)
                label = theme.render_cached(name, 15, theme.WHITE)
                surface.blit(label, (CARD_X + 48, y + (ROW_H - label.get_height()) // 2))
                icons.draw_chevron_right(surface, CARD_X + CARD_W - 14, y + ROW_H // 2, col)
                i += 1
        surface.set_clip(clip)

        minibar.draw(surface, self.app, status)

    # ── input ─────────────────────────────────────────────────────────────────

    def _index_at(self, y: int) -> int | None:
        rel = y - _TOP + self._scroll
        for i, top in enumerate(self._rows):
            if top <= rel < top + ROW_H:
                return i
        return None

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
            i = self._index_at(y)
            if i is not None:
                self._sel = i
                self._tap.set(self._open)
                return None
        return super().handle_touch(x, y)

    def handle_scroll(self, dy: float) -> None:
        self._scroll = max(0.0, min(self._max_scroll, self._scroll - dy))

    def _keep_visible(self) -> None:
        top = self._rows[self._sel]
        view = _BOTTOM - _TOP
        if top < self._scroll:
            self._scroll = max(0.0, top - HEAD_H)
        elif top + ROW_H > self._scroll + view:
            self._scroll = min(self._max_scroll, top + ROW_H - view)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = (self._sel - 1) % len(MENU)
            self._keep_visible()
        elif button == Button.DOWN:
            self._sel = (self._sel + 1) % len(MENU)
            self._keep_visible()
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



