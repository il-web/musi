"""Mini now-playing bar — geometry, hit zones, redraw caching."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import minibar


class FakeStatus:
    def __init__(self, title="", artist="", path="", state="stop"):
        self.title = title
        self.artist = artist
        self.path = path
        self.state = state
        self.album = ""
        self.connected = True
        self.duration = 0.0
        self.progress = 0.0


class FakeApp:
    db = None


def test_geometry_is_the_bottom_44px():
    assert minibar.BAR_H == 44
    assert minibar.BAR_Y == 436
    assert minibar.BAR_Y + minibar.BAR_H == 480


def test_hit_above_the_bar_is_none():
    assert minibar.hit(160, 435) is None


def test_hit_on_the_control_toggles():
    assert minibar.hit(300, 458) == "toggle"


def test_hit_on_the_body_opens_now_playing():
    assert minibar.hit(100, 458) == "open"


def test_draw_paints_the_bar_region():
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    minibar.draw(surface, FakeApp(), FakeStatus(title="Song", artist="Band"))
    # something was drawn in the bar, nothing above it
    assert surface.get_at((160, 450))[:3] != (0, 0, 0)
    assert surface.get_at((160, 400))[:3] == (0, 0, 0)


def test_idle_bar_still_draws():
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    minibar.draw(surface, FakeApp(), FakeStatus())
    assert surface.get_at((160, 450))[:3] != (0, 0, 0)
