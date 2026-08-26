"""Wallpaper picker — three options, applied and persisted on tap."""
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.player import prefs, wallpaper
from musi.player.screens.customization import (
    CustomizationScreen, LABEL_Y, OPTIONS, tile_rect,
)


class FakeApp:
    def __init__(self):
        self.stack = []

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        pass

    def request_poll(self):
        pass


class FakeStatus:
    title = "Song"
    artist = "Band"
    album = ""
    path = ""
    state = "play"
    connected = True
    duration = 100.0
    progress = 0.5


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    prefs.reload()
    wallpaper.clear_cache()
    yield
    prefs.reload()
    wallpaper.clear_cache()


def _tap(screen, i):
    """Tap option i and let PendingTap's flash delay elapse."""
    r = tile_rect(i)
    screen.handle_touch(r.centerx, r.centery)
    time.sleep(0.15)
    screen._tap.update()


def test_offers_none_warm_and_cool():
    assert [name for name, _ in OPTIONS] == ["none", "warm", "cool"]


def test_every_option_matches_a_known_wallpaper():
    assert all(name in wallpaper.NAMES for name, _ in OPTIONS)


def test_tiles_fit_the_screen_and_do_not_overlap():
    rects = [tile_rect(i) for i in range(len(OPTIONS))]
    assert rects[0].left >= 0 and rects[-1].right <= 320
    for a, b in zip(rects, rects[1:]):
        assert a.right < b.left


@pytest.mark.parametrize("index,expected", [(1, "warm"), (2, "cool"), (0, "none")])
def test_tapping_an_option_persists_it(index, expected):
    # Start from a value this case does not expect, so the "none" case cannot
    # pass simply by being the default.
    prefs.set("wallpaper", "cool" if expected == "warm" else "warm")
    screen = CustomizationScreen(FakeApp())
    _tap(screen, index)
    assert prefs.get("wallpaper") == expected


def test_tapping_the_caption_below_a_tile_selects_it():
    """The text label under a thumbnail must be tappable too, not just the
    thumbnail itself — a caption is a natural thing to press on a touchscreen."""
    prefs.set("wallpaper", "none")
    screen = CustomizationScreen(FakeApp())
    screen.draw(pygame.Surface((320, 480)), FakeStatus())  # renders the labels

    rect = tile_rect(1)  # "warm"
    caption_point = (rect.centerx, LABEL_Y + 2)  # inside the label text, below the tile
    assert caption_point[1] >= rect.bottom, "point must actually be past the tile"

    screen.handle_touch(*caption_point)
    time.sleep(0.15)
    screen._tap.update()
    assert prefs.get("wallpaper") == "warm"


def test_choice_survives_a_reload():
    screen = CustomizationScreen(FakeApp())
    _tap(screen, 1)
    prefs.reload()
    assert prefs.get("wallpaper") == "warm"


def test_draws_without_error_for_every_stored_choice():
    surface = pygame.Surface((320, 480))
    for name, _ in OPTIONS:
        prefs.set("wallpaper", name)
        CustomizationScreen(FakeApp()).draw(surface, FakeStatus())


def test_draw_does_no_file_io_after_the_first_frame(monkeypatch):
    surface = pygame.Surface((320, 480))
    screen = CustomizationScreen(FakeApp())
    screen.draw(surface, FakeStatus())

    loads = []
    real_load = pygame.image.load
    monkeypatch.setattr(pygame.image, "load",
                        lambda p: (loads.append(p), real_load(p))[1])
    for _ in range(10):
        screen.draw(surface, FakeStatus())
    assert loads == []
