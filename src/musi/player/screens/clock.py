"""Clock app — big digital time, no seconds, no alarms.

No seconds means the panel is genuinely static between minute ticks, so the
idle frame rate costs nothing. The Pi Zero W has no RTC, so until the device
has reached NTP since boot the time is a guess and the screen says so.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pygame

from musi.player import audio_detect, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

_TIMESYNC_DIR = Path("/run/systemd/timesync")
_SYNC_MARKER  = _TIMESYNC_DIR / "synchronized"

HM_Y   = 150      # baseline-ish top of the HH:MM block
DATE_Y = 236
HINT_Y = 262

_MONTHS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
           "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")
_DAYS   = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
           "SATURDAY", "SUNDAY")


def format_now(now: datetime) -> tuple[str, str]:
    """('22:14', 'WEDNESDAY, 5 AUGUST')."""
    return (now.strftime("%H:%M"),
            f"{_DAYS[now.weekday()]}, {now.day} {_MONTHS[now.month - 1]}")


def time_synced() -> bool:
    """True once systemd-timesyncd has set the clock.

    Machines without timesyncd at all (any dev box) report synced — the hint
    exists for the Pi booting offline, not to nag during development.
    """
    if not _TIMESYNC_DIR.exists():
        return True
    return _SYNC_MARKER.exists()


class ClockScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._minute   = -1
        self._hm_surf:   pygame.Surface | None = None
        self._date_surf: pygame.Surface | None = None
        self._hint_surf: pygame.Surface | None = None

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        now = datetime.now()
        minute = now.hour * 60 + now.minute
        if minute != self._minute:
            self._minute = minute
            hm, date = format_now(now)
            self._hm_surf   = theme.render(hm, 64, theme.WHITE)
            self._date_surf = theme.render(date, 12, theme.DIM)
            self._hint_surf = (None if time_synced() else
                               theme.render("time not synced", 10, (200, 150, 90)))

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)

        surface.blit(self._hm_surf, self._hm_surf.get_rect(centerx=160, y=HM_Y))
        surface.blit(self._date_surf,
                     self._date_surf.get_rect(centerx=160, y=DATE_Y))
        if self._hint_surf:
            surface.blit(self._hint_surf,
                         self._hint_surf.get_rect(centerx=160, y=HINT_Y))

        minibar.draw(surface, self.app, status)

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return None
        return super().handle_touch(x, y)
