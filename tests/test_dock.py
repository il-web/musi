"""Merged dock — now-playing strip over the nav row."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import dock, theme


class FakeStatus:
    title = "Song"
    artist = "Band"
    album = ""
    path = ""
    state = "play"
    connected = True
    duration = 0.0
    progress = 0.0


class FakeApp:
    db = None


def test_geometry_is_the_bottom_74px():
    assert dock.DOCK_Y == 406
    assert dock.DOCK_H == 74
    assert dock.NAV_Y == 450
    assert dock.NAV_H == 30
    assert dock.DOCK_Y + dock.DOCK_H == 480
    assert dock.NAV_Y + dock.NAV_H == 480


def test_three_tabs_today():
    assert [k for k, _ in dock.TABS] == ["home", "library", "search"]


def test_tab_width_comes_from_the_tab_list():
    """Adding Radio later must not need a layout change."""
    assert dock.tab_width() == 320 // len(dock.TABS)


def test_above_the_dock_is_not_a_hit():
    assert dock.hit(160, 405) is None


def test_nav_row_taps_resolve_to_tabs():
    assert dock.hit(20, 460) == ("tab", 0)
    assert dock.hit(160, 460) == ("tab", 1)
    assert dock.hit(300, 460) == ("tab", 2)


def test_tap_past_the_last_tab_clamps():
    """320 // 3 = 106, so x=318 lands on index 3 without a clamp."""
    assert dock.hit(319, 460) == ("tab", 2)


def test_strip_taps_toggle_and_open():
    assert dock.hit(300, 420) == ("toggle", 0)
    assert dock.hit(100, 420) == ("open", 0)


def test_draw_paints_the_dock_and_nothing_above_it():
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    dock.draw(surface, FakeApp(), FakeStatus(), active=0, accent=theme.ACCENT)
    assert surface.get_at((160, 420))[:3] != (0, 0, 0)   # strip
    assert surface.get_at((20, 460))[:3] != (0, 0, 0)    # nav
    assert surface.get_at((160, 400))[:3] == (0, 0, 0)   # above


def test_strip_can_be_suppressed_for_search():
    """Search keeps the nav row but hides the now-playing strip."""
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    dock.draw(surface, FakeApp(), FakeStatus(), active=2, accent=theme.ACCENT,
              strip=False)
    assert surface.get_at((160, 420))[:3] == (0, 0, 0)   # strip not drawn
    assert surface.get_at((20, 460))[:3] != (0, 0, 0)    # nav still there
