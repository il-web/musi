"""QueueScreen — save-as-playlist button and the row menu."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.mpd_client import QueueItem
from musi.player.screens import queue as q
from musi.player.screens.queue import QueueScreen


class FakeMPD:
    def __init__(self, items):
        self._items = items
        self.calls = []

    def queue(self):
        return list(self._items)

    def save_queue_as(self, name):
        self.calls.append(("save_queue_as", name))

    def play_pos(self, pos):
        self.calls.append(("play_pos", pos))

    def remove_pos(self, pos):
        self.calls.append(("remove_pos", pos))

    def move(self, a, b):
        self.calls.append(("move", a, b))


class FakeApp:
    db = None

    def __init__(self, items):
        self.mpd = FakeMPD(items)
        self.stack = []
        from musi.player.mpd_client import PlayerStatus
        self.status = PlayerStatus(state="stop", path="", title="", artist="",
                                   album="", elapsed=0.0, duration=0.0, volume=0,
                                   shuffle=False, repeat=False, queue_pos=0,
                                   queue_len=len(items))

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def request_poll(self):
        pass

    def toggle_play(self):
        pass


def _screen(items):
    app = FakeApp(items)
    s = QueueScreen(app)
    app.stack.append(s)
    s.on_enter()
    return s, app


def test_save_button_opens_the_text_prompt():
    s, app = _screen([QueueItem(0, "One", "A", "/m/1.mp3")])
    s.handle_touch(q.SAVE_RECT.centerx, q.SAVE_RECT.centery)
    assert type(app.stack[-1]).__name__ == "TextEntryScreen"


def test_save_button_is_inert_when_the_queue_is_empty():
    s, app = _screen([])
    s.handle_touch(q.SAVE_RECT.centerx, q.SAVE_RECT.centery)
    assert app.stack == [s]


def test_row_menu_offers_add_to_playlist_when_a_path_is_known():
    s, app = _screen([QueueItem(0, "One", "A", "/m/1.mp3")])
    assert s.handle_long_press(120, q.LIST_Y + 4) is True
    labels = [label for label, _cb in app.stack[-1]._options]
    assert "Add to playlist…" in labels


def test_row_menu_hides_add_to_playlist_without_a_path():
    s, app = _screen([QueueItem(0, "One", "A", "")])
    s.handle_long_press(120, q.LIST_Y + 4)
    labels = [label for label, _cb in app.stack[-1]._options]
    assert "Add to playlist…" not in labels
