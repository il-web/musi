"""Clock app — formatting, sync detection, minute-granularity redraw."""
import os
from datetime import datetime

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens import clock as clock_mod


class FakeStatus:
    title = ""
    artist = ""
    album = ""
    path = ""
    state = "stop"
    connected = True
    duration = 0.0
    progress = 0.0


class FakeApp:
    db = None
    stack = []


def test_format_now():
    hm, date = clock_mod.format_now(datetime(2026, 8, 5, 22, 14))
    assert hm == "22:14"
    assert date == "WEDNESDAY, 5 AUGUST"


def test_format_pads_the_hour():
    hm, _ = clock_mod.format_now(datetime(2026, 8, 5, 9, 4))
    assert hm == "09:04"


def test_time_synced_reads_the_systemd_marker(monkeypatch, tmp_path):
    marker = tmp_path / "synchronized"
    monkeypatch.setattr(clock_mod, "_SYNC_MARKER", marker)
    monkeypatch.setattr(clock_mod, "_TIMESYNC_DIR", tmp_path)
    assert clock_mod.time_synced() is False
    marker.write_text("")
    assert clock_mod.time_synced() is True


def test_time_synced_true_when_the_marker_dir_is_absent(monkeypatch, tmp_path):
    # dev machines have no systemd-timesyncd — assume synced rather than nag
    monkeypatch.setattr(clock_mod, "_SYNC_MARKER", tmp_path / "no" / "such")
    monkeypatch.setattr(clock_mod, "_TIMESYNC_DIR", tmp_path / "no")
    assert clock_mod.time_synced() is True


def test_draw_paints_the_time_and_the_minibar():
    from musi.player import minibar, theme
    surface = pygame.Surface((320, 480))
    s = clock_mod.ClockScreen(FakeApp())
    s.draw(surface, FakeStatus())
    # ClockScreen fills with theme.BG, so "drawn" means "not the background"
    row = [surface.get_at((x, clock_mod.HM_Y + 30))[:3] for x in range(60, 260)]
    assert any(px != theme.BG for px in row), "no digits drawn"
    assert surface.get_at((160, minibar.BAR_Y + 20))[:3] != theme.BG


def test_text_surfaces_are_reused_within_a_minute():
    s = clock_mod.ClockScreen(FakeApp())
    surface = pygame.Surface((320, 480))
    s.draw(surface, FakeStatus())
    first = s._hm_surf
    s.draw(surface, FakeStatus())
    assert s._hm_surf is first
