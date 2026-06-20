"""Home screen — main menu with mini now-playing card."""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

# Menu items: (label, screen_import_fn)
MENU = [
    "Now Playing",
    "Browse Library",
    "Search",
    "WiFi Transfer",
    "Settings",
]

CARD_Y    = 28      # mini now-playing card top
CARD_H    = 96      # card height
MENU_Y    = CARD_Y + CARD_H + 8    # first menu item y  (28+96+8 = 132)
ITEM_H    = 48      # height per menu item  (5 × 48 = 240 → bottom at 372)
NAV_Y     = 456


class HomeScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._sel        = 0               # selected menu index
        self._art:       pygame.Surface | None = None
        self._accent:    tuple = theme.ACCENT
        self._cached_path: str | None = "UNSET"

        # cached text
        self._title_surf: pygame.Surface | None = None
        self._meta_surf:  pygame.Surface | None = None
        self._prev_title: str = ""
        self._prev_meta:  str = ""

        # static (built on first draw)
        self._nav_surf:   pygame.Surface | None = None
        self._menu_surfs: list[pygame.Surface] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._reload_art(self.app.status)

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf   = theme.render("Enter = select   Esc = back", 10, theme.WHITE)
            self._menu_surfs = [theme.render(m, 15, theme.WHITE) for m in MENU]

        self._reload_art(status)
        self._update_text(status)

        # ── background ────────────────────────────────────────────────────────
        surface.fill(theme.BG)

        # ── status bar ────────────────────────────────────────────────────────
        statusbar.draw(surface, status, audio_detect.get_audio_type())

        # ── mini now-playing card ─────────────────────────────────────────────
        card_rect = pygame.Rect(10, CARD_Y, 300, CARD_H)
        pygame.draw.rect(surface, theme.CARD_BG, card_rect, border_radius=8)

        if self._art:
            # album art on left
            surface.blit(self._art, (18, CARD_Y + 10))
            # accent left border
            pygame.draw.rect(surface, self._accent,
                             pygame.Rect(10, CARD_Y, 4, CARD_H), border_radius=4)
        else:
            # placeholder square
            pygame.draw.rect(surface, (40, 40, 55),
                             pygame.Rect(18, CARD_Y + 10, 76, 76), border_radius=4)
            _draw_music_note(surface, 56, CARD_Y + 48, (80, 80, 100))

        # track info (right of art)
        tx = 104
        if self._title_surf:
            surface.blit(self._title_surf, (tx, CARD_Y + 14))
        if self._meta_surf:
            surface.blit(self._meta_surf, (tx, CARD_Y + 36))

        # tiny play state icon
        state_col = self._accent if status.state == "play" else (100, 100, 115)
        if status.state == "play":
            _mini_pause(surface, 302, CARD_Y + 16, state_col)
        else:
            _mini_play(surface, 302, CARD_Y + 16, state_col)

        # progress bar at bottom of card
        if status.duration > 0:
            bw = 278
            pygame.draw.rect(surface, (40, 40, 55), (18, CARD_Y + CARD_H - 12, bw, 4), border_radius=2)
            filled = max(4, int(bw * status.progress))
            pygame.draw.rect(surface, self._accent, (18, CARD_Y + CARD_H - 12, filled, 4), border_radius=2)

        # ── menu items ────────────────────────────────────────────────────────
        for i, label_surf in enumerate(self._menu_surfs):
            y = MENU_Y + i * ITEM_H
            item_rect = pygame.Rect(10, y, 300, ITEM_H - 4)

            if i == self._sel:
                # selected: filled accent background
                pygame.draw.rect(surface, self._accent, item_rect, border_radius=8)
                _draw_item_icon(surface, i, 36, y + (ITEM_H - 4) // 2, theme.WHITE)
                surface.blit(label_surf, (60, y + (ITEM_H - label_surf.get_height()) // 2 - 2))
                # chevron
                _draw_chevron(surface, 296, y + (ITEM_H - 4) // 2, theme.WHITE)
            else:
                # unselected: card bg
                pygame.draw.rect(surface, theme.CARD_BG, item_rect, border_radius=8)
                _draw_item_icon(surface, i, 36, y + (ITEM_H - 4) // 2, theme.DIM)
                dim_surf = theme.render(MENU[i], 15, theme.DIM)
                surface.blit(dim_surf, (60, y + (ITEM_H - dim_surf.get_height()) // 2 - 2))
                _draw_chevron(surface, 296, y + (ITEM_H - 4) // 2, theme.CARD_BG)

        # ── nav hint ──────────────────────────────────────────────────────────
        surface.blit(self._nav_surf, self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        # Tap mini now-playing card → play/pause
        if CARD_Y <= y < CARD_Y + CARD_H:
            return Button.PLAY_PAUSE
        # Tap a menu item → open it directly
        if MENU_Y <= y < MENU_Y + len(MENU) * ITEM_H:
            i = (y - MENU_Y) // ITEM_H
            if 0 <= i < len(MENU):
                self._sel = i
                self._open_selected()
                return None
        return super().handle_touch(x, y)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = (self._sel - 1) % len(MENU)
        elif button == Button.DOWN:
            self._sel = (self._sel + 1) % len(MENU)
        elif button == Button.PLAY_PAUSE:
            self.app.mpd.play_pause()
        elif button == Button.SELECT:
            self._open_selected()

    def _open_selected(self) -> None:
        if self._sel == 0:
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
        elif self._sel == 1:
            from musi.player.screens.browse import BrowseScreen
            self.app.push(BrowseScreen(self.app))
        elif self._sel == 2:
            from musi.player.screens.search import SearchScreen
            self.app.push(SearchScreen(self.app))
        elif self._sel == 3:
            from musi.player.screens.usb import USBScreen
            self.app.push(USBScreen(self.app))
        elif self._sel == 4:
            from musi.player.screens.settings import SettingsScreen
            self.app.push(SettingsScreen(self.app))

    # ── art / text ────────────────────────────────────────────────────────────

    def _reload_art(self, status: PlayerStatus) -> None:
        if status.path == self._cached_path:
            return
        self._cached_path = status.path
        self._art    = None
        self._accent = theme.ACCENT

        if not status.path:
            return

        row = self.app.db.execute(
            """SELECT al.art_path, al.palette
               FROM tracks t JOIN albums al ON al.id = t.album_id
               WHERE t.path = ?""",
            (status.path,),
        ).fetchone()

        if not row and status.artist and status.album:
            row = self.app.db.execute(
                """SELECT al.art_path, al.palette
                   FROM albums al JOIN artists ar ON ar.id = al.artist_id
                   WHERE ar.name = ? AND al.title = ?""",
                (status.artist, status.album),
            ).fetchone()

        if not row:
            return

        if row["art_path"] and Path(row["art_path"]).exists():
            try:
                img = pygame.image.load(row["art_path"]).convert()
                self._art = pygame.transform.scale(img, (76, 76))
            except Exception:
                pass

        if row["palette"]:
            try:
                colours = json.loads(row["palette"])
                if colours:
                    self._accent = theme.hex_to_rgb(colours[0])
                    # ensure accent is bright enough to be visible on dark BG
                    r, g, b = self._accent
                    if r + g + b < 180:
                        self._accent = theme.brighten(self._accent, 1.8)
            except Exception:
                pass

    def _update_text(self, status: PlayerStatus) -> None:
        title = status.title or ("musi" if not status.connected else "Nothing playing")
        meta  = status.artist or ""

        if title != self._prev_title:
            self._prev_title  = title
            self._title_surf  = theme.render(title, 13, theme.WHITE, bold=True, max_width=180)

        if meta != self._prev_meta:
            self._prev_meta  = meta
            self._meta_surf  = theme.render(meta, 11, theme.DIM, max_width=180)


# ── icon helpers ──────────────────────────────────────────────────────────────

def _draw_item_icon(surface, index, cx, cy, colour):
    """Draw a simple icon for each menu item."""
    if index == 0:   # Now Playing — play triangle
        pts = [(cx - 7, cy - 8), (cx - 7, cy + 8), (cx + 8, cy)]
        pygame.draw.polygon(surface, colour, pts)
    elif index == 1: # Browse — three lines
        for dy in (-5, 0, 5):
            pygame.draw.line(surface, colour, (cx - 8, cy + dy), (cx + 8, cy + dy), 2)
    elif index == 2: # Search — magnifier
        pygame.draw.circle(surface, colour, (cx - 2, cy - 2), 6, 2)
        pygame.draw.line(surface, colour, (cx + 3, cy + 3), (cx + 8, cy + 8), 2)
    elif index == 3: # WiFi Transfer — WiFi arcs
        import math
        for r, a in [(10, 0.55), (6, 0.6), (2, 0.0)]:
            if r == 2:
                pygame.draw.circle(surface, colour, (cx, cy + 4), 2)
            else:
                pts = [
                    (cx + int(r * math.cos(math.pi * 0.5 + math.pi * a * t / 20)),
                     cy + 4 - int(r * math.sin(math.pi * 0.5 + math.pi * a * t / 20)))
                    for t in range(-20, 21)
                ]
                pygame.draw.lines(surface, colour, False, pts, 2)
    elif index == 4: # Settings — gear
        pygame.draw.circle(surface, colour, (cx, cy), 7, 2)
        pygame.draw.circle(surface, colour, (cx, cy), 3)


def _draw_chevron(surface, cx, cy, colour):
    pts = [(cx - 4, cy - 6), (cx + 2, cy), (cx - 4, cy + 6)]
    pygame.draw.lines(surface, colour, False, pts, 2)


def _draw_music_note(surface, cx, cy, colour):
    pygame.draw.circle(surface, colour, (cx - 5, cy + 4), 5)
    pygame.draw.line(surface, colour, (cx, cy + 4), (cx, cy - 10), 2)
    pygame.draw.line(surface, colour, (cx, cy - 10), (cx + 8, cy - 14), 2)
    pygame.draw.line(surface, colour, (cx + 8, cy - 14), (cx + 8, cy - 4), 2)


def _mini_play(surface, cx, cy, colour):
    pts = [(cx - 4, cy - 7), (cx - 4, cy + 7), (cx + 7, cy)]
    pygame.draw.polygon(surface, colour, pts)


def _mini_pause(surface, cx, cy, colour):
    pygame.draw.rect(surface, colour, (cx - 6, cy - 7, 4, 14), border_radius=1)
    pygame.draw.rect(surface, colour, (cx + 2, cy - 7, 4, 14), border_radius=1)
