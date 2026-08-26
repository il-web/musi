"""LauncherScreen — page routing, tap vs swipe, subtitles, mini bar."""
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


class FakeApp:
    def __init__(self, db):
        self.db = db
        self.mpd = FakeMPD()
        self.stack = []
        self.remaining = None

    def push(self, screen):
        self.stack.append(screen)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        self.mpd.calls.append(("toggle_play",))

    def sleep_remaining(self):
        return self.remaining

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
    return FakeApp(conn)


def _launcher(app):
    from musi.player.screens.launcher import LauncherScreen
    s = LauncherScreen(app)
    app.stack.append(s)
    return s


def test_four_apps_in_order(app):
    s = _launcher(app)
    assert [k for k, _ in s.APPS] == [
        "music", "settings", "clock", "sleep", "customization"]


def test_tap_on_the_tile_opens_the_app(app):
    s = _launcher(app)
    s.on_press(160, 160)
    s.on_release(160, 160)
    assert app.stack[-1].__class__.__name__ == "MusicScreen"


def test_swipe_does_not_open_an_app(app):
    s = _launcher(app)
    s.on_press(240, 160)
    s.on_drag(60, 160)
    s.on_release(60, 160)
    assert len(app.stack) == 1


def test_swipe_left_advances_to_settings(app):
    s = _launcher(app)
    s.on_press(240, 160)
    s.on_drag(60, 160)
    s.on_release(60, 160)
    while s._car.update():
        pass
    assert s._car.index == 1
    s.on_press(160, 160)
    s.on_release(160, 160)
    assert app.stack[-1].__class__.__name__ == "SettingsScreen"


def test_swipe_right_wraps_to_customization(app):
    s = _launcher(app)
    s.on_press(60, 160)
    s.on_drag(240, 160)
    s.on_release(240, 160)
    while s._car.update():
        pass
    assert s._car.index == 4
    s.on_press(160, 160)
    s.on_release(160, 160)
    assert app.stack[-1].__class__.__name__ == "CustomizationScreen"


def test_clock_page_opens_clock(app):
    s = _launcher(app)
    s._car.index = 2
    s.on_press(160, 160)
    s.on_release(160, 160)
    assert app.stack[-1].__class__.__name__ == "ClockScreen"


def test_minibar_tap_opens_now_playing(app):
    s = _launcher(app)
    s.on_press(100, 458)
    s.on_release(100, 458)
    assert app.stack[-1].__class__.__name__ == "NowPlayingScreen"


def test_minibar_control_toggles(app):
    s = _launcher(app)
    s.on_press(300, 458)
    s.on_release(300, 458)
    assert ("toggle_play",) in app.mpd.calls


def test_music_subtitle_counts_albums(app):
    s = _launcher(app)
    assert s.subtitle("music") == "3 albums"


def test_sleep_subtitle_reflects_the_timer(app):
    s = _launcher(app)
    assert s.subtitle("sleep") == "Off"
    app.remaining = 2400.0
    assert s.subtitle("sleep") == "41 min left"


def test_animates_only_while_snapping(app):
    s = _launcher(app)
    assert s.animates is False
    s.on_press(240, 160)
    s.on_drag(60, 160)
    s.on_release(60, 160)
    assert s.animates is True


def test_draw_runs_on_every_page(app):
    surface = pygame.Surface((320, 480))
    s = _launcher(app)
    for i in range(len(s.APPS)):
        s._car.index = i
        s.draw(surface, FakeStatus())


def test_draw_mid_drag_runs(app):
    surface = pygame.Surface((320, 480))
    s = _launcher(app)
    s.on_press(240, 160)
    s.on_drag(180, 160)
    s.draw(surface, FakeStatus())
