"""TextEntryScreen — the shared single-line prompt."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.input import Button
from musi.player.screens.text_entry import TextEntryScreen


class FakeApp:
    def __init__(self):
        self.stack = []

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()


def _status():
    from musi.player.mpd_client import PlayerStatus
    return PlayerStatus(state="stop", path="", title="", artist="", album="",
                        elapsed=0.0, duration=0.0, volume=50, shuffle=False,
                        repeat=False, queue_pos=-1, queue_len=0)


def _screen(initial=""):
    app = FakeApp()
    got = []
    s = TextEntryScreen(app, "Name it", initial=initial,
                        on_commit=got.append)
    app.stack.append(s)
    return s, app, got


def test_on_screen_keys_accumulate_and_draw():
    s, _, _ = _screen()
    for ch in "hey":
        s._on_key(ch)
    s._on_key("SPACE")
    s._on_key("y")
    assert s._text == "hey y"
    s.draw(pygame.Surface((320, 480)), _status())      # must not raise


def test_hardware_keyboard_typing():
    s, _, _ = _screen()
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x")
    assert s.handle_event(ev) is True
    assert s._text == "x"


def test_commit_trims_pops_and_calls_back():
    s, app, got = _screen(initial="  Beach  ")
    s._on_key("ENTER")
    assert got == ["Beach"]
    assert app.stack == []


def test_empty_commit_is_a_no_op():
    s, app, got = _screen(initial="   ")
    s._on_key("ENTER")
    assert got == []
    assert app.stack == [s]


def test_back_deletes_then_pops():
    s, app, got = _screen(initial="ab")
    s.handle(Button.BACK, _status())
    assert s._text == "a"
    s.handle(Button.BACK, _status())
    assert s._text == ""
    s.handle(Button.BACK, _status())          # now empty → leave the screen
    assert app.stack == []
    assert got == []


def test_max_len_is_enforced():
    s, _, _ = _screen()
    for _ in range(60):
        s._on_key("a")
    assert len(s._text) == 40
