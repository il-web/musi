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


def test_browse_defaults_match_todays_geometry(app):
    from musi.player.screens.browse import BrowseScreen
    s = BrowseScreen(app)
    assert (s.list_y, s.nav_y) == (62, 456)


def test_browse_accepts_a_reduced_content_rect(app):
    from musi.player.screens.browse import BrowseScreen
    s = BrowseScreen(app, list_y=58, nav_y=436)
    assert (s.list_y, s.nav_y, s._klist.view_h) == (58, 436, 378)


def test_browse_hit_testing_follows_the_injected_rect(app):
    from musi.player.screens.browse import BrowseScreen
    s = BrowseScreen(app, list_y=58, nav_y=436)
    # a tap 2px above the injected list top must not select a row
    s.handle_touch(160, 56)
    assert s._tap.pending is False


def test_history_accepts_a_reduced_content_rect(app):
    from musi.player.screens.history import HistoryScreen
    s = HistoryScreen(app, mode="recent", list_y=58, nav_y=436)
    assert (s.list_y, s.nav_y) == (58, 436)


def test_history_mode_still_positional(app):
    from musi.player.screens.history import HistoryScreen
    s = HistoryScreen(app, "most")
    assert s.list_y == 62


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
    from musi.player.screens import browse, history
    for mod in (browse, history):
        assert "Esc = back" not in inspect.getsource(mod)
