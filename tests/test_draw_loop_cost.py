"""The render loop must not do I/O.

Both regressions these cover were introduced by the launcher pack and showed up
on the Pi Zero W as audio stutter: the UI process starving MPD of a single ARMv6
core. Neither is visible in a screenshot, so they are pinned here instead.
"""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db, run_migrations
import pytest


class CountingDB:
    """Wraps a connection and counts queries so a test can assert 'none'."""

    def __init__(self, conn):
        self._conn = conn
        self.queries = 0

    def execute(self, *args, **kwargs):
        self.queries += 1
        return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class FakeApp:
    def __init__(self, db):
        self.db = db
        self.stack = []

    def push(self, screen):
        self.stack.append(screen)

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
    path = "/m/t1.mp3"
    state = "play"
    connected = True
    duration = 100.0
    progress = 0.5


@pytest.fixture
def app(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    artist = conn.execute("INSERT INTO artists (name) VALUES ('Artist')").lastrowid
    for n in range(3):
        conn.execute(
            "INSERT INTO albums (artist_id, title, year) VALUES (?, ?, 2025)",
            (artist, f"Album {n}"))
    conn.commit()
    return FakeApp(CountingDB(conn))


def test_launcher_draw_does_no_sql_after_the_first_frame(app):
    """A COUNT(*) per frame is ~30 queries/second on the screen you sit on most."""
    from musi.player.screens.launcher import LauncherScreen
    surface = pygame.Surface((320, 480))
    s = LauncherScreen(app)
    app.stack.append(s)
    s.on_enter()
    s.draw(surface, FakeStatus())

    app.db.queries = 0
    for _ in range(20):
        s.draw(surface, FakeStatus())
    assert app.db.queries == 0


def test_launcher_still_reports_the_album_count(app):
    from musi.player.screens.launcher import LauncherScreen
    s = LauncherScreen(app)
    assert s.subtitle("music") == "3 albums"


def test_on_enter_picks_up_a_changed_library(app):
    """Returning from the Music app must not show a stale count."""
    from musi.player.screens.launcher import LauncherScreen
    s = LauncherScreen(app)
    assert s.subtitle("music") == "3 albums"
    app.db.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (1, 'New', 2026)")
    s.on_enter()
    assert s.subtitle("music") == "4 albums"


def test_load_surface_is_cached(tmp_path):
    """minibar reloads art on every track change, on every screen that has it."""
    from musi.player import art_cache
    png = tmp_path / "art.png"
    pygame.image.save(pygame.Surface((64, 64)), str(png))
    first = art_cache.load_surface(str(png), (32, 32))
    assert first is not None
    assert art_cache.load_surface(str(png), (32, 32)) is first


def test_load_surface_caches_per_size(tmp_path):
    from musi.player import art_cache
    png = tmp_path / "art2.png"
    pygame.image.save(pygame.Surface((64, 64)), str(png))
    assert (art_cache.load_surface(str(png), (32, 32))
            is not art_cache.load_surface(str(png), (48, 48)))


def test_minibar_reload_is_skipped_for_an_unchanged_track(app):
    """The per-frame guard must hold, or every frame pays a SQL join + image load."""
    from musi.player import minibar
    surface = pygame.Surface((320, 480))
    minibar.draw(surface, app, FakeStatus())

    app.db.queries = 0
    for _ in range(20):
        minibar.draw(surface, app, FakeStatus())
    assert app.db.queries == 0
