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


def _multi_library(tmp_path, n_albums: int):
    """n albums, each with one played track — every shelf has n covers."""
    conn = open_db(tmp_path / "multi.db")
    run_migrations(conn)
    ar = conn.execute("INSERT INTO artists (name) VALUES ('A')").lastrowid
    for i in range(n_albums):
        al = conn.execute(
            "INSERT INTO albums (artist_id, title, year) VALUES (?, ?, 2020)",
            (ar, f"Alb{i}")).lastrowid
        t = conn.execute(
            """INSERT INTO tracks (album_id, artist_id, path, title, file_mtime)
               VALUES (?, ?, ?, 'T', ?)""",
            (al, ar, f"/m/{i}.mp3", 100 + i)).lastrowid
        conn.execute(
            "INSERT INTO play_history (track_id, played_at) VALUES (?, ?)",
            (t, 5 + i))
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


def _has_bright_pixel(surface, rect) -> bool:
    x0, y0, w, h = rect
    for x in range(x0, x0 + w, 2):
        for y in range(y0, y0 + h, 2):
            if max(surface.get_at((x, y))[:3]) > 80:
                return True
    return False


def test_empty_library_draws_an_empty_state(tmp_path):
    conn = open_db(tmp_path / "empty.db")
    run_migrations(conn)
    s = HomeScreen(FakeApp(conn))
    s.on_enter()
    surface = pygame.Surface((320, 480))
    surface.fill((0, 0, 0))
    s.draw(surface, FakeStatus())
    assert s.is_empty
    # draw() actually rendered the empty-state text in the centre band...
    assert _has_bright_pixel(surface, (60, 190, 200, 60))
    # ...and left the area below it as plain background.
    assert not _has_bright_pixel(surface, (60, 300, 200, 80))


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


# ── vertical scroll of the shelf region ──────────────────────────────────────

def test_three_shelves_have_a_scrollable_extent(tmp_path):
    from musi.player.screens import home
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    assert len(s.shelves) == 3
    assert s._max_scroll == 3 * home.SHELF_H - 320 == 130


def test_one_shelf_does_not_scroll(tmp_path):
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=False)))
    s.on_enter()
    assert len(s.shelves) == 1
    assert s._max_scroll == 0


def test_scrolled_to_the_end_the_third_shelf_is_fully_visible(tmp_path):
    """The regression: at y >= nav_y the old code broke the loop and the third
    shelf drew entirely under the dock."""
    from musi.player.screens import home
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    s.handle_scroll(-10_000)                 # scroll to the bottom
    assert s._scroll == s._max_scroll
    art_top = home.FIRST_Y + 2 * home.SHELF_H - s._scroll + home.LABEL_H
    art_bottom = art_top + home.CELL
    assert art_top >= home.FIRST_Y
    assert art_bottom <= s.nav_y


def test_scroll_clamps_at_both_ends(tmp_path):
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    s.handle_scroll(-10_000)
    assert s._scroll == s._max_scroll
    s.handle_scroll(10_000)
    assert s._scroll == 0.0


def test_vertical_drag_scrolls_the_page_and_not_the_shelf(tmp_path):
    from musi.player.screens import home
    s = HomeScreen(FakeApp(_multi_library(tmp_path, 8)))
    s.on_enter()
    y = home.FIRST_Y + home.LABEL_H + 10
    shelf = s.shelves[0][2]
    s.on_press(160, y)
    s.on_drag(158, y - 80)                   # predominantly vertical
    s.on_release(158, y - 80)
    assert s._scroll > 0
    assert shelf.first_visible() == 0 and shelf.pixel_shift() == 0


def test_horizontal_drag_moves_the_shelf_and_not_the_page(tmp_path):
    from musi.player.screens import home
    s = HomeScreen(FakeApp(_multi_library(tmp_path, 8)))
    s.on_enter()
    y = home.FIRST_Y + home.LABEL_H + 10
    shelf = s.shelves[0][2]
    s.on_press(220, y)
    s.on_drag(140, y + 2)                    # predominantly horizontal
    s.on_release(140, y + 2)
    assert s._scroll == 0.0
    assert shelf.pixel_shift() != 0


def test_shelf_at_follows_the_scroll(tmp_path):
    from musi.player.screens import home
    s = HomeScreen(FakeApp(_library(tmp_path, with_history=True)))
    s.on_enter()
    s.handle_scroll(-10_000)                 # third shelf now near the top
    art_top = home.FIRST_Y + 2 * home.SHELF_H - s._scroll + home.LABEL_H
    hit = s._shelf_at(int(art_top) + 5)
    assert hit is not None
    assert hit[1] is s.shelves[2][2]
