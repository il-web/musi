"""Wallpaper loading — cached, cropped, and never touching disk twice."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.player import wallpaper


@pytest.fixture(autouse=True)
def clean():
    wallpaper.clear_cache()
    yield
    wallpaper.clear_cache()


@pytest.mark.parametrize("name", ["warm", "cool"])
def test_stock_wallpapers_load_at_the_page_size(name):
    s = wallpaper.surface(name)
    assert s is not None, f"{name} failed to load — is the asset committed?"
    assert s.get_size() == (wallpaper.WIDTH, wallpaper.HEIGHT)


def test_none_has_no_surface():
    assert wallpaper.surface("none") is None


def test_unknown_name_has_no_surface():
    assert wallpaper.surface("nonsense") is None


def test_surface_is_cached_not_reloaded():
    """Reloading per frame is the exact mistake test_draw_loop_cost guards."""
    first = wallpaper.surface("warm")
    assert wallpaper.surface("warm") is first


def test_a_failed_load_is_cached_too(monkeypatch):
    """A missing file must not be retried from disk on every frame."""
    calls = []

    def counting_load(path):
        calls.append(path)
        raise pygame.error("no such file")

    monkeypatch.setattr(wallpaper.pygame.image, "load", counting_load)
    assert wallpaper.surface("warm") is None
    assert wallpaper.surface("warm") is None
    assert len(calls) == 1


def test_thumbnail_is_scaled_and_cached():
    first = wallpaper.thumbnail("warm", (84, 108))
    assert first is not None
    assert first.get_size() == (84, 108)
    assert wallpaper.thumbnail("warm", (84, 108)) is first


def test_thumbnail_of_none_is_none():
    assert wallpaper.thumbnail("none", (84, 108)) is None


def test_names_are_the_three_picker_options():
    assert wallpaper.NAMES == ("none", "warm", "cool")
