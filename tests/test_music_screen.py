"""Music host — three tabs and the dock that switches them."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db, run_migrations
from musi.player import dock
from musi.player.screens import music
from musi.player.screens.home import HomeScreen
from musi.player.screens.library import LibraryScreen
from musi.player.screens.music import MusicHostScreen


class FakeApp:
    def __init__(self, db):
        self.db = db
        self.stack = []
        self.toggled = 0

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        self.toggled += 1

    def request_poll(self):
        pass


class FakeStatus:
    title = "Song"
    artist = "Band"
    album = ""
    path = ""
    state = "play"
    connected = True
    duration = 0.0
    progress = 0.0


@pytest.fixture
def app(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    ar = conn.execute("INSERT INTO artists (name) VALUES ('A')").lastrowid
    conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, 'Alb', 2020)",
        (ar,))
    conn.commit()
    return FakeApp(conn)


def test_starts_on_home(app):
    h = MusicHostScreen(app)
    assert h.tab == 0
    assert isinstance(h.child, HomeScreen)


def test_tab_one_is_library(app):
    h = MusicHostScreen(app)
    h.set_tab(1)
    assert isinstance(h.child, LibraryScreen)


def test_children_are_kept_so_scroll_survives(app):
    h = MusicHostScreen(app)
    first = h.child
    h.set_tab(1)
    h.set_tab(0)
    assert h.child is first


def test_nav_tap_switches_tab(app):
    h = MusicHostScreen(app)
    h.handle_touch(160, 460)          # middle tab
    assert h.tab == 1


def test_strip_tap_toggles_play(app):
    h = MusicHostScreen(app)
    h.handle_touch(300, 420)
    assert app.toggled == 1


def test_strip_body_opens_now_playing(app):
    h = MusicHostScreen(app)
    h.handle_touch(100, 420)
    assert app.stack, "tapping the strip body should push Now Playing"


def test_search_tab_keeps_the_nav_row(app):
    """Hiding the whole dock on Search would trap you on that tab."""
    h = MusicHostScreen(app)
    h.set_tab(music.SEARCH_TAB)
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    h.draw(surface, FakeStatus())
    assert surface.get_at((20, 460))[:3] != (0, 0, 0)


def test_search_keyboard_ends_exactly_on_the_nav_row():
    from musi.player.keyboard import Keyboard
    from musi.player.screens.search import KB_TOP
    assert KB_TOP + Keyboard().height == dock.NAV_Y
