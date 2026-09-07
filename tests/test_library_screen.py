"""Library — pill filters over an album grid and an artist list."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db, run_migrations
from musi.player.screens import library
from musi.player.screens.library import LibraryScreen


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
def db(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    for n, name in enumerate(("Alpha", "Beta")):
        ar = conn.execute("INSERT INTO artists (name) VALUES (?)",
                          (name,)).lastrowid
        conn.execute(
            "INSERT INTO albums (artist_id, title, year) VALUES (?, ?, 2020)",
            (ar, f"Album {n}"))
    conn.commit()
    return conn


def test_grid_geometry_fills_the_width():
    assert library.COLS == 3
    assert library.CELL == 93
    assert library.MARGIN * 2 + library.COLS * library.CELL \
        + (library.COLS - 1) * library.GAP <= 320


def test_two_pills_today_with_room_for_playlists():
    assert library.PILLS == ["Albums", "Artists"]


def test_albums_pill_loads_albums(db):
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    assert [i.label for i in s.items] == ["Album 0", "Album 1"]


def test_artists_pill_loads_artists_as_rows(db):
    """artists has no art — it must not render as a grid."""
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    s.set_pill(1)
    assert [i.label for i in s.items] == ["Alpha", "Beta"]
    assert s.item_h == library.ARTIST_H


def test_albums_pill_uses_the_grid_row_height(db):
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    assert s.item_h == library.ROW_H


def test_switching_pills_resets_the_scroll(db):
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    s._klist.offset = 40.0
    s.set_pill(1)
    assert s._klist.offset == 0.0


def test_draw_does_no_sql_after_the_first_frame(db):
    app = FakeApp(CountingDB(db))
    s = LibraryScreen(app)
    s.on_enter()
    surface = pygame.Surface((320, 480))
    s.draw(surface, FakeStatus())

    app.db.queries = 0
    for _ in range(20):
        s.draw(surface, FakeStatus())
    assert app.db.queries == 0


def test_empty_library_draws_without_crashing(tmp_path):
    conn = open_db(tmp_path / "empty.db")
    run_migrations(conn)
    s = LibraryScreen(FakeApp(conn))
    s.on_enter()
    s.draw(pygame.Surface((320, 480)), FakeStatus())
    assert s.items == []


def test_tapping_an_artist_drills_into_their_albums(db):
    """Artists drill in inside Library — no new screen is pushed."""
    app = FakeApp(db)
    s = LibraryScreen(app)
    s.on_enter()
    s.set_pill(1)
    s._sel = 0
    s._select()
    assert app.stack == [], "the drill-in must not push a screen"
    assert s.artist_name == "Alpha"
    assert [i.label for i in s.items] == ["Album 0"]


def test_go_up_returns_to_the_artist_list(db):
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    s.set_pill(1)
    s._sel = 0
    s._select()
    s.go_up()
    assert s.artist_id == 0
    assert [i.label for i in s.items] == ["Alpha", "Beta"]
