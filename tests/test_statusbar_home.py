"""The status bar's Home affordance."""
import inspect
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import icons, statusbar
from musi.player.mpd_client import PlayerStatus


def test_draw_accepts_show_home():
    assert "show_home" in inspect.signature(statusbar.draw).parameters


def test_show_back_is_gone():
    """A leftover show_back= keyword would silently draw nothing."""
    assert "show_back" not in inspect.signature(statusbar.draw).parameters


def _lit(surface, box):
    """Count non-black pixels inside a bounding box."""
    x0, y0, x1, y1 = box
    return sum(
        surface.get_at((x, y))[:3] != (0, 0, 0)
        for x in range(x0, x1) for y in range(y0, y1)
    )


def test_the_home_glyph_paints_pixels():
    s = pygame.Surface((40, 40))
    s.fill((0, 0, 0))
    icons.draw_home(s, 20, 20, (255, 255, 255))
    assert _lit(s, (10, 10, 31, 31)) > 0


def test_the_home_glyph_stays_within_the_chevrons_footprint():
    """The logo shifts by a fixed 28px, so the glyph must not overrun it."""
    s = pygame.Surface((40, 40))
    s.fill((0, 0, 0))
    icons.draw_home(s, 20, 20, (255, 255, 255))
    assert _lit(s, (0, 0, 40, 40)) == _lit(s, (12, 12, 29, 29))


def test_the_bar_draws_with_home_shown():
    s = pygame.Surface((320, 480))
    statusbar.draw(s, PlayerStatus.disconnected(), "wired", show_home=True)


def test_the_bar_draws_without_home():
    s = pygame.Surface((320, 480))
    statusbar.draw(s, PlayerStatus.disconnected(), "wired")
