"""Playback settings — crossfade, volume leveling (ReplayGain), ListenBrainz.

Three rows: two switches that take effect at once (pref + MPD command), and a
row that opens the ListenBrainz sign-in. Switch prefs are re-applied to MPD at
startup by the loading screen, since MPD keeps both in its own state file.
"""
from __future__ import annotations

import pygame

from musi.library import listenbrainz
from musi.player import audio_detect, icons, minibar, motion, prefs, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import SWITCH_W, draw_switch

# Seconds MPD blends over when crossfade is on. Zero is how MPD spells "off",
# so the pref is a bool and this is the only place the duration is named.
CROSSFADE_S = 2

# (key, title, subtitle). key: a bool pref toggled in place, or "listenbrainz"
ROWS: list[tuple[str, str, str]] = [
    ("crossfade",    "Crossfade",       f"Blend tracks over {CROSSFADE_S}s"),
    ("replaygain",   "Volume leveling", "ReplayGain — for files tagged with it"),
    ("listenbrainz", "ListenBrainz",    ""),
]

ROW_X, ROW_W = 10, 300
ROW_H        = 62
ROW_Y        = 72
ROW_GAP      = 10
KNOB_S       = 0.18


def row_rect(i: int) -> pygame.Rect:
    return pygame.Rect(ROW_X, ROW_Y + i * (ROW_H + ROW_GAP), ROW_W, ROW_H)


class PlaybackScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._header: pygame.Surface | None = None
        self._knobs = {key: motion.Tween(KNOB_S) for key, _, _ in ROWS}

    @property
    def animates(self) -> bool:
        return any(t.active() for t in self._knobs.values())

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header is None:
            self._header = theme.render("Playback", 16, theme.WHITE, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(self._header, (14, 34))

        for i, (key, title, sub) in enumerate(ROWS):
            r = row_rect(i)
            pygame.draw.rect(surface, theme.CARD_BG, r, border_radius=8)
            surface.blit(theme.render(title, 15, theme.WHITE), (r.x + 16, r.y + 11))
            if key == "listenbrainz":
                sub = _listenbrainz_line()
            surface.blit(theme.render(sub, 10, theme.DIM, max_width=r.w - 90),
                         (r.x + 16, r.y + 36))
            if key == "listenbrainz":
                icons.draw_chevron_right(surface, r.right - 16, r.centery, theme.DIM)
            else:
                on = bool(prefs.get(key))
                k = motion.ease_out_cubic(self._knobs[key].progress())
                draw_switch(surface, r.right - 16 - SWITCH_W, r.centery,
                            k if on else 1 - k)

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

        for i, (key, _, _) in enumerate(ROWS):
            if row_rect(i).collidepoint(x, y):
                self.activate(key)
                return None
        return super().handle_touch(x, y)

    def activate(self, key: str) -> None:
        if key == "listenbrainz":
            from musi.player.screens.listenbrainz import ListenBrainzScreen
            self.app.push(ListenBrainzScreen(self.app))
            return
        on = not bool(prefs.get(key))
        prefs.set(key, on)
        self._knobs[key].start()
        if key == "crossfade":
            self.app.mpd.set_crossfade(CROSSFADE_S if on else 0)
        elif key == "replaygain":
            self.app.mpd.set_replay_gain(on)


def _listenbrainz_line() -> str:
    s = listenbrainz.load_settings()
    if not s:
        return "Not connected — scrobble what you play"
    return f"Scrobbling as {s.get('user', '?')}"
