"""MusicScreen tab host — construction, forwarding, tab switching."""
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

    def toggle_play(self):
        self.mpd.calls.append(("toggle_play",))


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
    album = conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, 'Album', 2025)",
        (artist,)).lastrowid
    conn.execute(
        "INSERT INTO tracks (album_id, artist_id, path, title, track_number, duration)"
        " VALUES (?,?,?,?,?,?)",
        (album, artist, "/m/t1.mp3", "Track 1", 1, 100.0))
    conn.commit()
    return FakeApp(conn)


def _music(app, tab=0):
    from musi.player.screens.music import MusicScreen
    s = MusicScreen(app, tab=tab)
    app.stack.append(s)
    return s


def test_four_tabs(app):
    from musi.player.screens.music import MusicScreen
    assert MusicScreen.TABS == ["Browse", "Search", "Recent", "Most"]


def test_browse_child_gets_the_reduced_content_rect(app):
    s = _music(app)
    assert (s.child.list_y, s.child.nav_y) == (58, 436)


def test_recent_and_most_are_separate_history_modes(app):
    s = _music(app)
    s.set_tab(2)
    recent = s.child
    s.set_tab(3)
    assert s.child is not recent
    assert (recent._mode, s.child._mode) == ("recent", "most")


def test_search_child_is_offset_below_the_tab_strip(app):
    s = _music(app, tab=1)
    assert s.child.box_y == 62


def test_tab_tap_switches_tabs(app):
    s = _music(app)
    s.handle_touch(120, 40)          # second of four 80px tabs
    assert s.tab == 1


def test_content_tap_forwards_to_the_child(app):
    s = _music(app)
    calls = []
    s.child.handle_touch = lambda x, y: calls.append((x, y))
    s.handle_touch(160, 200)
    assert calls == [(160, 200)]


def test_scroll_forwards_to_the_child(app):
    s = _music(app)
    calls = []
    s.child.handle_scroll = lambda dy: calls.append(dy)
    s.handle_scroll(-30)
    assert calls == [-30]


def test_minibar_tap_opens_now_playing(app):
    s = _music(app)
    s.handle_touch(100, 458)
    assert app.stack[-1].__class__.__name__ == "NowPlayingScreen"


def test_minibar_control_toggles_playback(app):
    s = _music(app)
    s.handle_touch(300, 458)
    assert ("toggle_play",) in app.mpd.calls


def test_search_tab_swallows_minibar_taps(app):
    s = _music(app, tab=1)
    calls = []
    s.child.handle_touch = lambda x, y: calls.append((x, y))
    s.handle_touch(100, 458)
    assert calls == [(100, 458)]        # went to the keyboard, not the bar
    assert app.stack[-1] is s


def test_draw_runs_for_every_tab(app):
    surface = pygame.Surface((320, 480))
    s = _music(app)
    for i in range(4):
        s.set_tab(i)
        s.draw(surface, FakeStatus())


def test_browse_crumb_is_none_at_the_artist_level(app):
    s = _music(app)
    s.child.on_enter()
    assert s.child.crumb is None


def test_album_level_swaps_the_tab_strip_for_a_breadcrumb(app):
    s = _music(app)
    s.child.on_enter()
    s.child._select()                # step into the artist
    assert s.child.crumb == "Artist"


def test_breadcrumb_tap_goes_up_instead_of_switching_tabs(app):
    s = _music(app)
    s.child.on_enter()
    s.child._select()
    s.handle_touch(120, 40)          # the Search tab's x, but the band is a crumb
    assert s.tab == 0
    assert s.child.crumb is None     # went back to the artist list


def test_breadcrumb_surface_is_cached_between_frames(app):
    surface = pygame.Surface((320, 480))
    s = _music(app)
    s.child.on_enter()
    s.child._select()
    s.draw(surface, FakeStatus())
    first = s._crumb_surf
    assert first is not None
    s.draw(surface, FakeStatus())
    assert s._crumb_surf is first


def test_tabs_return_after_leaving_the_album_level(app):
    surface = pygame.Surface((320, 480))
    s = _music(app)
    s.child.on_enter()
    s.child._select()
    s.child.go_up()
    s.draw(surface, FakeStatus())
    s.handle_touch(120, 40)
    assert s.tab == 1                # tab strip is back, tap switches again


def test_switching_tabs_fires_lifecycle(app):
    s = _music(app)
    events = []
    s.child.on_exit = lambda: events.append("exit")
    s.set_tab(1)
    s.child.on_enter = lambda: events.append("enter")
    s.set_tab(0)
    assert "exit" in events
