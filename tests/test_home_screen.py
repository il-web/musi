"""Home — greeting, shelves, and the empty states a fresh device hits."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db, run_migrations
from musi.player.screens.home import HomeScreen, greeting


class CountingDB:
    def __init__(self, conn):
        self._conn = conn
        self.queries = 0

    def execute(self, *a, **k):
        self.queries += 1
        return self._conn.execute(*a, **k)

    def __getattr__(self, name):
        return getattr(self._conn, name)


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


def _library(tmp_path, with_history: bool):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    ar = conn.execute("INSERT INTO artists (name) VALUES ('A')").lastrowid
    al = conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, 'Alb', 2020)",
        (ar,)).lastrowid
    t = conn.execute(
        """INSERT INTO tracks (album_id, artist_id, path, title, file_mtime)
           VALUES (?, ?, '/m/1.mp3', 'T', 100)""", (al, ar)).lastrowid
    if with_history:
        conn.execute(
            "INSERT INTO play_history (track_id, played_at) VALUES (?, 5)", (t,))
    conn.commit()
    return conn


@pytest.mark.parametrize("hour,expected", [
    (0,  "Good night"),
    (5,  "Good morning"),
    (11, "Good morning"),
    (12, "Good afternoon"),
    (17, "Good afternoon"),
    (18, "Good evening"),
    (21, "Good evening"),
    (22, "Good night"),
])
def test_greeting_by_hour(hour, expected):
    assert greeting(hour) == expected


def test_fresh_device_shows_only_new_in_your_library(tmp_path):
    """play_history is empty on every clean install — no empty shelves."""
    app = FakeApp(_library(tmp_path, with_history=False))
    s = HomeScreen(app)
    s.on_enter()
    assert [title for title, _, _ in s.shelves] == ["New in your library"]


def test_played_library_shows_all_three_shelves(tmp_path):
    app = FakeApp(_library(tmp_path, with_history=True))
    s = HomeScreen(app)
    s.on_enter()
    assert [title for title, _, _ in s.shelves] == [
        "Recently played", "New in your library", "Most played"]


def test_empty_library_has_no_shelves(tmp_path):
    conn = open_db(tmp_path / "empty.db")
    run_migrations(conn)
    s = HomeScreen(FakeApp(conn))
    s.on_enter()
    assert s.shelves == []


def test_empty_library_draws_an_empty_state(tmp_path):
    conn = open_db(tmp_path / "empty.db")
    run_migrations(conn)
    s = HomeScreen(FakeApp(conn))
    s.on_enter()
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    s.draw(surface, FakeStatus())
    assert s.is_empty


def test_draw_does_no_sql_after_the_first_frame(tmp_path):
    """A query per frame starves MPD of a core — audible as audio stutter."""
    app = FakeApp(CountingDB(_library(tmp_path, with_history=True)))
    s = HomeScreen(app)
    s.on_enter()
    surface = pygame.Surface((320, 480))
    s.draw(surface, FakeStatus())

    app.db.queries = 0
    for _ in range(20):
        s.draw(surface, FakeStatus())
    assert app.db.queries == 0


def _shelf_y(screen):
    """A y inside the first shelf's art band."""
    from musi.player.screens import home
    return home.FIRST_Y + home.LABEL_H + 10


def test_press_on_a_shelf_captures_the_gesture(tmp_path):
    """Without capture, on_drag never fires and shelves cannot scroll."""
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    assert s.on_press(50, _shelf_y(s)) is True


def test_press_off_a_shelf_does_not_capture(tmp_path):
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    assert s.on_press(50, 40) is False


def test_a_tap_opens_the_album(tmp_path):
    app = FakeApp(_library(tmp_path, with_history=True))
    s = HomeScreen(app)
    s.on_enter()
    y = _shelf_y(s)
    s.on_press(50, y)
    s.on_release(50, y)
    assert app.stack, "a tap on a cover should open the album"


def test_a_drag_scrolls_instead_of_opening(tmp_path):
    app = FakeApp(_library(tmp_path, with_history=True))
    s = HomeScreen(app)
    s.on_enter()
    y = _shelf_y(s)
    s.on_press(200, y)
    s.on_drag(100, y)
    s.on_release(100, y)
    assert app.stack == [], "a drag must not be treated as a tap"


def test_animates_does_not_advance_the_shelves(tmp_path):
    """Reading .animates must be side-effect free — draw() owns update()."""
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    assert s.animates is False
    assert s.animates is False
