"""AlbumScreen tests — dummy SDL, seeded temp DB, fake app/mpd."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from musi.library.db import open_db, run_migrations

pygame.init()
pygame.display.set_mode((320, 480))


class FakeMPD:
    def __init__(self):
        self.calls = []

    def play_paths(self, paths, start_index=0):
        self.calls.append(("play_paths", list(paths), start_index))

    def set_shuffle(self, on):
        self.calls.append(("set_shuffle", on))

    def queue_next(self, paths):
        self.calls.append(("queue_next", list(paths)))

    def queue_add(self, paths):
        self.calls.append(("queue_add", list(paths)))


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
    for n in range(1, 7):                      # 6 tracks x 100s = 10 min
        conn.execute(
            "INSERT INTO tracks (album_id, artist_id, path, title, track_number, duration)"
            " VALUES (?,?,?,?,?,?)",
            (album, artist, f"/m/t{n}.mp3", f"Track {n}", n, 100.0))
    conn.commit()
    a = FakeApp(conn)
    a.album_id = album
    return a


def _screen(app):
    from musi.player.screens.album import AlbumScreen
    s = AlbumScreen(app, app.album_id)
    app.stack.append(s)
    s.on_enter()
    return s


def _status():
    from musi.player.mpd_client import PlayerStatus
    return PlayerStatus(state="stop", path="", title="", artist="", album="",
                        elapsed=0.0, duration=0.0, volume=50, shuffle=False,
                        repeat=False, queue_pos=-1, queue_len=0)


def test_loads_and_renders(app):
    s = _screen(app)
    assert s._album_title == "Album"
    assert s._artist_name == "Artist"
    assert len(s._tracks) == 6
    assert s._meta_line == "6 songs · 10 min"
    s.draw(pygame.Surface((320, 480)), _status())   # must not raise


def test_play_button(app):
    from musi.player.screens.album import PLAY_RECT
    s = _screen(app)
    s.handle_touch(PLAY_RECT.centerx, PLAY_RECT.centery)
    assert app.mpd.calls[0] == ("set_shuffle", False)
    assert app.mpd.calls[1][0] == "play_paths"
    assert app.mpd.calls[1][2] == 0                     # from track 1
    assert len(app.mpd.calls[1][1]) == 6
    assert len(app.stack) == 2                          # Now Playing pushed


def test_shuffle_button(app):
    from musi.player.screens.album import SHUFFLE_RECT
    s = _screen(app)
    s.handle_touch(SHUFFLE_RECT.centerx, SHUFFLE_RECT.centery)
    assert app.mpd.calls[0] == ("set_shuffle", True)
    name, paths, start = app.mpd.calls[1]
    assert name == "play_paths" and 0 <= start < 6


def test_track_tap_plays_from_index(app):
    import time
    s = _screen(app)
    s.handle_touch(160, s.list_y + s.item_h + 4)        # second visible row
    time.sleep(0.15)                                    # PendingTap flash window
    s._tap.update()
    calls = [c for c in app.mpd.calls if c[0] == "play_paths"]
    assert calls and calls[0][2] == 1
    assert not any(c[0] == "set_shuffle" for c in app.mpd.calls)


def test_long_press_opens_menu(app):
    s = _screen(app)
    assert s.handle_long_press(160, s.list_y + 4) is True
    assert len(app.stack) == 2                          # context menu pushed


def test_hour_formatting():
    from musi.player.screens.album import _fmt_total
    assert _fmt_total(43 * 60) == "43 min"
    assert _fmt_total(72 * 60) == "1 hr 12 min"
    assert _fmt_total(30) == "<1 min"
