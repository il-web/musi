"""App tiles — size, caching, transparency outside the rounded corners."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import app_tiles
import pytest


def test_four_keys():
    assert app_tiles.KEYS == ("music", "settings", "clock", "sleep", "customization")


def test_tile_is_square_and_118_by_default():
    surf = app_tiles.render_tile("music")
    assert surf.get_size() == (118, 118)


def test_custom_size():
    assert app_tiles.render_tile("clock", 64).get_size() == (64, 64)


def test_tiles_are_cached():
    assert app_tiles.render_tile("music") is app_tiles.render_tile("music")


def test_corners_are_transparent():
    surf = app_tiles.render_tile("music")
    assert surf.get_at((1, 1))[3] == 0


def test_centre_is_opaque():
    surf = app_tiles.render_tile("music")
    assert surf.get_at((59, 59))[3] == 255


def test_each_app_has_a_distinct_accent():
    accents = {app_tiles.accent(k) for k in app_tiles.KEYS}
    assert len(accents) == 5


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        app_tiles.render_tile("radio")
