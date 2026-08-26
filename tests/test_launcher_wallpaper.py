"""The launcher composites a wallpaper under its sliding pages."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.library.db import open_db, run_migrations
from musi.player import prefs, wallpaper
from musi.player.screens.launcher import LauncherScreen, PAGE_H, PAGE_Y


class FakeApp:
    def __init__(self, db):
        self.db = db
        self.stack = []

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        pass

    def sleep_remaining(self):
        return None

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


@pytest.fixture
def app(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    return FakeApp(conn)


def _draw(app):
    surface = pygame.Surface((320, 480))
    s = LauncherScreen(app)
    app.stack.append(s)
    s.on_enter()
    s.draw(surface, FakeStatus())
    return surface


def test_pages_are_transparent_so_the_wallpaper_shows_through(app):
    """An opaque page would hide the wallpaper and slide it sideways."""
    s = LauncherScreen(app)
    app.stack.append(s)
    page = s._page(0)
    assert page.get_flags() & pygame.SRCALPHA
    assert page.get_at((4, 4))[3] == 0, "page corner should be fully transparent"


def test_wallpaper_pixels_reach_the_screen(app):
    prefs.set("wallpaper", "warm")
    lit = _draw(app)
    prefs.set("wallpaper", "none")
    plain = _draw(app)
    probe = (8, PAGE_Y + 8)          # a corner the tile and scrim do not cover
    assert lit.get_at(probe) != plain.get_at(probe)


def test_no_wallpaper_still_renders(app):
    prefs.set("wallpaper", "none")
    plain = _draw(app)
    assert plain.get_at((8, PAGE_Y + 8))[:3] == (10, 10, 15)


def test_a_broken_wallpaper_name_falls_back_to_the_plain_background(app):
    prefs.set("wallpaper", "nonsense")
    surface = _draw(app)
    assert surface.get_at((8, PAGE_Y + 8))[:3] == (10, 10, 15)


def test_the_scrim_darkens_the_label_band(app):
    """Bright artwork sits right where the app name and subtitle are."""
    prefs.set("wallpaper", "warm")
    drawn = _draw(app)
    raw = wallpaper.surface("warm")
    band_y = PAGE_Y + LauncherScreen.SCRIM_Y + LauncherScreen.SCRIM_H // 2
    on_screen = drawn.get_at((4, band_y))[:3]
    original = raw.get_at((4, LauncherScreen.SCRIM_Y + LauncherScreen.SCRIM_H // 2))[:3]
    assert sum(on_screen) < sum(original), "scrim should darken the band"


def test_page_area_is_exactly_the_wallpaper_height():
    assert PAGE_H == wallpaper.HEIGHT
