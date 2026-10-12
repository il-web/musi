"""Artist page, and Now Playing's artist / album names that open it."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db, run_migrations
from musi.player import album_queries
from musi.player.screens import now_playing
from musi.player.screens.artist import ArtistScreen


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    ar = conn.execute("INSERT INTO artists (name) VALUES ('Daft Punk')").lastrowid
    other = conn.execute("INSERT INTO artists (name) VALUES ('Someone')").lastrowid
    n = 0
    for title, year in (("Homework", 1997), ("Discovery", 2001), ("RAM", 2013)):
        al = conn.execute("INSERT INTO albums (artist_id, title, year) VALUES (?, ?, ?)",
                          (ar, title, year)).lastrowid
        for k in range(3):
            n += 1
            conn.execute("INSERT INTO tracks (album_id, artist_id, path, title, track_number,"
                         " duration) VALUES (?, ?, ?, ?, ?, 200)",
                         (al, ar, f"/m/{n}.flac", f"{title} {k + 1}", k + 1))
    al = conn.execute("INSERT INTO albums (artist_id, title) VALUES (?, 'Theirs')",
                      (other,)).lastrowid
    conn.execute("INSERT INTO tracks (album_id, artist_id, path, title) VALUES (?, ?, '/m/x', 'x')",
                 (al, other))
    for _ in range(3):                                   # most played: Discovery 2
        conn.execute("INSERT INTO play_history (track_id) SELECT id FROM tracks WHERE title = 'Discovery 2'")
    conn.execute("INSERT INTO play_history (track_id) SELECT id FROM tracks WHERE title = 'RAM 1'")
    conn.commit()
    return conn


class FakeMPD:
    def __init__(self):
        self.calls = []

    def play_paths(self, paths, start_index=0):
        self.calls.append(("play", list(paths), start_index))

    def set_shuffle(self, on):
        self.calls.append(("shuffle", on))

    def is_favorite(self, path):
        return False

    def queue(self):
        return []


class Status:
    path = "/m/5.flac"
    title, artist, album = "Discovery 2", "Daft Punk", "Discovery"
    state, connected, duration, progress, elapsed = "play", True, 200.0, 0.1, 20.0
    volume, shuffle, repeat, queue_pos, queue_len = 50, False, False, 0, 1


class App:
    def __init__(self, db):
        self.db, self.mpd, self.stack, self.status = db, FakeMPD(), [], Status()
        self.lyrics_dir = None

    def push(self, s):
        self.stack.append(s)
        s.on_enter()

    def pop(self):
        self.stack.pop()

    def request_poll(self):
        pass

    def toggle_play(self):
        pass


def _artist(db, name="Daft Punk"):
    return album_queries.artist_id_by_name(db, name)


def test_artist_page_lists_top_songs_then_albums_newest_first(db):
    s = ArtistScreen(App(db), _artist(db))
    s.on_enter()
    kinds = [r[0] for r in s.rows]
    assert kinds == ["header", "song", "song", "header", "album", "album", "album"]
    assert [r[1]["title"] for r in s.rows if r[0] == "song"] == ["Discovery 2", "RAM 1"]
    assert [r[1]["title"] for r in s.rows if r[0] == "album"] == ["RAM", "Discovery", "Homework"]
    assert s._stats == "3 albums · 9 songs"
    assert s.rows[s._sel][0] != "header"
    s.draw(pygame.Surface((320, 480)), Status())        # must not raise


def test_play_queues_everything_by_them_and_albums_open(db):
    app = App(db)
    s = ArtistScreen(app, _artist(db))
    s.on_enter()
    s.play(shuffle=False)
    played = app.mpd.calls[-1]
    assert played[0] == "play" and len(played[1]) == 9 and "/m/x" not in played[1]
    album_row = next(i for i, r in enumerate(s.rows) if r[0] == "album")
    s._open(album_row)
    assert type(app.stack[-1]).__name__ == "AlbumScreen"


def test_artist_without_history_has_no_top_songs(db):
    s = ArtistScreen(App(db), _artist(db, "Someone"))
    s.on_enter()
    assert [r[0] for r in s.rows] == ["header", "album"]


def test_now_playing_artist_and_album_names_open_their_pages(db):
    app = App(db)
    s = now_playing.NowPlayingScreen(app)
    surf = pygame.Surface((320, 480))
    s.draw(surf, app.status)
    left = 160 - s._meta_surf.get_width() // 2
    s.handle_touch(left + 4, now_playing.ARTIST_Y + 6)                 # on "Daft Punk"
    assert type(app.stack[-1]).__name__ == "ArtistScreen"
    assert app.stack[-1].name == "Daft Punk"
    s.handle_touch(left + s._meta_surf.get_width() - 4, now_playing.ARTIST_Y + 6)  # "Discovery"
    assert type(app.stack[-1]).__name__ == "AlbumScreen"


def test_now_playing_names_do_nothing_for_radio(db):
    app = App(db)
    app.status.path = "http://stream.example/live"
    app.status.artist, app.status.album = "Some Station", ""
    s = now_playing.NowPlayingScreen(app)
    s.draw(pygame.Surface((320, 480)), app.status)
    s.handle_touch(160, now_playing.ARTIST_Y + 6)
    assert app.stack == []
