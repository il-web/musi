"""PlaylistScreen — play / reorder / remove a stored playlist."""
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens import playlist as pl
from musi.player.screens.playlist import PlaylistScreen


def _tracks(n):
    return [{"path": f"/m/t{i}.mp3", "title": f"Track {i}", "artist": "A",
             "duration": 60.0} for i in range(n)]


class FakeMPD:
    def __init__(self, tracks):
        self._tracks = tracks
        self.calls = []

    def playlist_tracks(self, name):
        return list(self._tracks)

    def play_paths(self, paths, start_index=0):
        self.calls.append(("play_paths", list(paths), start_index))

    def set_shuffle(self, on):
        self.calls.append(("set_shuffle", on))

    def queue_next(self, paths):
        self.calls.append(("queue_next", list(paths)))

    def queue_add(self, paths):
        self.calls.append(("queue_add", list(paths)))

    def playlist_move(self, name, frm, to):
        self.calls.append(("playlist_move", name, frm, to))

    def playlist_remove_at(self, name, pos):
        self.calls.append(("playlist_remove_at", name, pos))
        self._tracks.pop(pos)


class FakeApp:
    db = None

    def __init__(self, mpd):
        self.mpd = mpd
        self.stack = []

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def request_poll(self):
        pass

    def toggle_play(self):
        pass


def _status():
    from musi.player.mpd_client import PlayerStatus
    return PlayerStatus(state="stop", path="", title="", artist="", album="",
                        elapsed=0.0, duration=0.0, volume=50, shuffle=False,
                        repeat=False, queue_pos=-1, queue_len=0)


def _screen(n=5, name="Road trip"):
    app = FakeApp(FakeMPD(_tracks(n)))
    s = PlaylistScreen(app, name)
    app.stack.append(s)
    s.on_enter()
    return s, app


def test_loads_tracks_and_meta():
    s, _ = _screen(5)
    assert len(s._tracks) == 5
    assert s._meta_line == "5 songs · 5 min"
    s.draw(pygame.Surface((320, 480)), _status())      # must not raise


def test_favorites_name_still_renders():
    s, _ = _screen(2, name="Favorites")
    s.draw(pygame.Surface((320, 480)), _status())


def test_play_button_plays_from_the_top():
    s, app = _screen(4)
    s.handle_touch(pl.PLAY_RECT.centerx, pl.PLAY_RECT.centery)
    assert app.mpd.calls[0] == ("set_shuffle", False)
    assert app.mpd.calls[1][0] == "play_paths"
    assert app.mpd.calls[1][2] == 0
    assert type(app.stack[-1]).__name__ == "NowPlayingScreen"


def test_track_tap_plays_from_that_index():
    s, app = _screen(4)
    s.handle_touch(120, s.list_y + s.item_h + 4)       # second row
    time.sleep(0.15)
    s._tap.update()
    plays = [c for c in app.mpd.calls if c[0] == "play_paths"]
    assert plays and plays[0][2] == 1


def test_long_press_menu_has_remove():
    s, app = _screen(3)
    assert s.handle_long_press(120, s.list_y + 4) is True
    menu = app.stack[-1]
    assert type(menu).__name__ == "ContextMenuScreen"
    assert [label for label, _cb in menu._options][-1] == "Remove from playlist"


def test_drag_the_handle_reorders_via_mpd():
    s, app = _screen(5)
    grabbed = s.on_press(pl.HANDLE_X, s.list_y + 4)    # row 0 handle
    assert grabbed is True
    s.on_drag(pl.HANDLE_X, s.list_y + int(s.item_h * 2.5))   # → row 2
    s.on_release(pl.HANDLE_X, s.list_y + int(s.item_h * 2.5))
    assert ("playlist_move", "Road trip", 0, 2) in app.mpd.calls


def test_a_non_move_drag_does_not_call_mpd():
    s, app = _screen(5)
    s.on_press(pl.HANDLE_X, s.list_y + 4)
    s.on_release(pl.HANDLE_X, s.list_y + 4)
    assert not any(c[0] == "playlist_move" for c in app.mpd.calls)
