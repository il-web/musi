"""List screens honour an injected content rect instead of module constants."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db, run_migrations
import pytest


class FakeMPD:
    def __init__(self):
        self.calls = []

    def play_paths(self, paths, start_index=0):
        self.calls.append(("play_paths", list(paths), start_index))


class FakeApp:
    def __init__(self, db):
        self.db = db
        self.mpd = FakeMPD()
        self.stack = []

    def push(self, screen):
        self.stack.append(screen)

    def pop(self):
        self.stack.pop()

    def request_poll(self):
        pass


@pytest.fixture
def app(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    artist = conn.execute("INSERT INTO artists (name) VALUES ('Artist')").lastrowid
    album = conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, 'Album', 2025)",
        (artist,)).lastrowid
    conn.execute(
        "INSERT INTO tracks (album_id, artist_id, path, title, track_number, duration)"
        " VALUES (?,?,?,?,?,?)",
        (album, artist, "/m/t1.mp3", "Track 1", 1, 100.0))
    conn.commit()
    return FakeApp(conn)


def test_library_defaults_match_todays_geometry(app):
    from musi.player.screens import library
    from musi.player.screens.library import LibraryScreen
    assert (library.LIST_Y, library.NAV_Y) == (98, 406)
    s = LibraryScreen(app)
    s.on_enter()
    assert (s.list_y, s.nav_y) == (98, 406)


def test_library_accepts_an_injected_content_rect(app):
    from musi.player.screens.library import LibraryScreen
    s = LibraryScreen(app, list_y=120, nav_y=380)
    s.on_enter()
    # the injected rect must propagate to the kinetic list's viewport height
    assert (s.list_y, s.nav_y, s._klist.view_h) == (120, 380, 260)


def test_library_hit_testing_follows_the_injected_rect(app):
    from musi.player.screens.library import LibraryScreen
    # inject a list top well below the module constant (98): a tap between the
    # two would land in the list under the constant but is above the injected rect
    s = LibraryScreen(app, list_y=140, nav_y=380)
    s.on_enter()
    s.handle_touch(160, 120)
    assert s._tap.pending is False


def test_search_shifts_its_box_with_top_y(app):
    from musi.player.screens.search import SearchScreen
    s = SearchScreen(app, top_y=58)
    assert s.box_y == 62
    assert s.list_y == 102


def test_search_defaults_match_todays_geometry(app):
    from musi.player.screens.search import SearchScreen
    s = SearchScreen(app)
    assert (s.box_y, s.list_y) == (30, 70)


def test_no_nav_hints_remain():
    import inspect
    from musi.player.screens import home, library
    for mod in (home, library):
        assert "Esc = back" not in inspect.getsource(mod)
