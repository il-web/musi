"""Library — pill filters over an album grid and an artist list."""
import math
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


@pytest.fixture
def db_multi(tmp_path):
    """One artist with four albums — the smallest library where

    ceil(n / COLS) differs from n, so the grid/list row-count mismatch and the
    unreachable-rows bug become visible.
    """
    conn = open_db(tmp_path / "multi.db")
    run_migrations(conn)
    ar = conn.execute("INSERT INTO artists (name) VALUES (?)",
                      ("Prolific",)).lastrowid
    for n in range(4):
        conn.execute(
            "INSERT INTO albums (artist_id, title, year) VALUES (?, ?, ?)",
            (ar, f"Rec {n}", 2000 + n))
    conn.commit()
    return conn


def _drill_into_prolific(db_multi):
    s = LibraryScreen(FakeApp(db_multi))
    s.on_enter()
    s.set_pill(1)
    s._sel = 0
    s._select()          # drill into the artist (inside Library, no push)
    return s


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


# ── artist drill-in renders and behaves as an album grid ─────────────────────

def test_drilled_in_artist_is_in_grid_mode_and_draws(db_multi):
    """Symptom 1: the drill-in must render as the grid, not artist cards."""
    s = _drill_into_prolific(db_multi)
    assert [i.label for i in s.items] == ["Rec 0", "Rec 1", "Rec 2", "Rec 3"]
    assert s._grid_mode is True
    # draws without crashing and stays in grid mode
    s.draw(pygame.Surface((320, 480)), FakeStatus())
    assert s._grid_mode is True


def test_drilled_in_draw_lays_out_grid_rows_not_item_rows(db_multi):
    """Symptom 2: draw must pass the same row count set_count received,

    else rows past the second land below the clip and cannot be scrolled to.
    """
    s = _drill_into_prolific(db_multi)
    assert s._klist.count == math.ceil(len(s.items) / library.COLS) == 2

    captured = []
    real = s.draw_list_viewport
    s.draw_list_viewport = lambda surface, n: (captured.append(n),
                                               real(surface, n))[1]
    s.draw(pygame.Surface((320, 480)), FakeStatus())
    assert captured == [s._klist.count]


def test_drilled_in_select_opens_the_album(db_multi):
    """Symptom 3: selecting an album in the drill-in must push AlbumScreen."""
    s = _drill_into_prolific(db_multi)
    s._sel = 2                     # "Rec 2" — a row past the first grid row
    s._select()
    assert len(s.app.stack) == 1
    assert type(s.app.stack[-1]).__name__ == "AlbumScreen"


def test_go_up_after_drill_returns_to_artist_pill(db_multi):
    s = _drill_into_prolific(db_multi)
    s.go_up()
    assert s.pill == 1
    assert s._grid_mode is False
    assert [i.label for i in s.items] == ["Prolific"]


# ── handle_touch hit-testing ────────────────────────────────────────────────

@pytest.mark.parametrize("col,expected", [(0, 0), (1, 1), (2, 2)])
def test_tap_maps_x_to_the_grid_column(db_multi, col, expected):
    s = LibraryScreen(FakeApp(db_multi))
    s.on_enter()                                  # Albums pill, 4 albums
    x = library.MARGIN + col * (library.CELL + library.GAP) + 4
    s.handle_touch(x, s.list_y + 4)
    assert s._sel == expected


def test_tap_on_a_pill_switches_pills(db):
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    s.draw(pygame.Surface((320, 480)), FakeStatus())   # populates _pill_rects
    rect = s._pill_rects[1]
    s.handle_touch(rect.centerx, rect.centery)
    assert s.pill == 1
    assert [i.label for i in s.items] == ["Alpha", "Beta"]


def test_tap_on_the_back_crumb_goes_up(db):
    s = LibraryScreen(FakeApp(db))
    s.on_enter()
    s.set_pill(1)
    s._sel = 0
    s._select()                                   # drilled into "Alpha"
    assert s.artist_id != 0
    s.handle_touch(20, 40)                         # y < PILL_Y, x < 120
    assert s.artist_id == 0
    assert [i.label for i in s.items] == ["Alpha", "Beta"]
