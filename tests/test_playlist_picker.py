"""AddToPlaylistScreen — pick a playlist (or make one) for some tracks."""
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens.playlist_picker import AddToPlaylistScreen


class FakeMPD:
    def __init__(self, playlists=()):
        from musi.player.mpd_client import PlaylistInfo
        self._pls = [PlaylistInfo(n, c) for n, c in playlists]
        self.calls = []

    def list_playlists(self):
        return list(self._pls)

    def playlist_add(self, name, paths):
        self.calls.append(("playlist_add", name, list(paths)))


class FakeApp:
    def __init__(self, mpd):
        self.mpd = mpd
        self.stack = []

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def request_poll(self):
        pass


def _status():
    from musi.player.mpd_client import PlayerStatus
    return PlayerStatus(state="stop", path="", title="", artist="", album="",
                        elapsed=0.0, duration=0.0, volume=50, shuffle=False,
                        repeat=False, queue_pos=-1, queue_len=0)


def _screen(playlists, paths=("/m/a.mp3",)):
    app = FakeApp(FakeMPD(playlists))
    s = AddToPlaylistScreen(app, list(paths))
    app.stack.append(s)
    s.on_enter()
    return s, app


def test_new_row_sits_above_the_playlists():
    s, _ = _screen([("Favorites", 2), ("Mix", 9)])
    assert len(s._rows) == 3
    assert s._rows[0].endswith("New playlist…")
    assert s._rows[1:] == ["Favorites", "Mix"]
    s.draw(pygame.Surface((320, 480)), _status())      # must not raise


def test_picking_a_playlist_adds_the_paths_and_pops():
    s, app = _screen([("Mix", 9)], paths=["/m/a.mp3", "/m/b.mp3"])
    s._pick(1)
    assert app.mpd.calls == [("playlist_add", "Mix", ["/m/a.mp3", "/m/b.mp3"])]
    assert s not in app.stack


def test_new_playlist_prompts_then_creates():
    s, app = _screen([("Mix", 9)])
    s._pick(0)
    entry = app.stack[-1]
    assert type(entry).__name__ == "TextEntryScreen"
    entry._text = "Beach"
    entry._commit()
    assert ("playlist_add", "Beach", ["/m/a.mp3"]) in app.mpd.calls


def test_tap_routes_through_the_pending_flash():
    s, app = _screen([("Mix", 9)])
    s.draw(pygame.Surface((320, 480)), _status())
    s.handle_touch(120, s.list_y + s.item_h + 4)       # the "Mix" row
    time.sleep(0.15)
    s._tap.update()
    assert app.mpd.calls == [("playlist_add", "Mix", ["/m/a.mp3"])]
