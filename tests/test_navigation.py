"""Back and Home primitives — the contract the swipe and the status bar share."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.app import App
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen


class Probe(Screen):
    """A minimal screen that records the lifecycle calls it receives."""

    def __init__(self, app, name):
        super().__init__(app)
        self.name = name
        self.entered = 0
        self.exited = 0

    def on_enter(self):
        self.entered += 1

    def on_exit(self):
        self.exited += 1

    def draw(self, surface, status):
        pass


def _app(tmp_path, depth):
    a = App(mpd=None, db=None, art_dir=tmp_path, lyrics_dir=tmp_path)
    for i in range(depth):
        a.push(Probe(a, f"s{i}"))
    return a


def test_go_back_pops_one_level(tmp_path):
    a = _app(tmp_path, 3)
    a.stack[-1].go_back()
    assert len(a.stack) == 2


def test_go_back_at_the_root_does_nothing(tmp_path):
    """The launcher is the root — there is nothing beneath it to fall to."""
    a = _app(tmp_path, 1)
    a.stack[-1].go_back()
    assert len(a.stack) == 1


def test_go_home_clears_to_the_root(tmp_path):
    a = _app(tmp_path, 4)
    root = a.stack[0]
    a.go_home()
    assert a.stack == [root]


def test_go_home_runs_each_screens_on_exit(tmp_path):
    """Popping one at a time rather than truncating the list is what keeps
    every screen's on_exit firing — screens release resources there."""
    a = _app(tmp_path, 4)
    above = a.stack[1:]
    # push() already fires on_exit on the screen it covers, so measure the
    # delta go_home itself causes rather than the absolute count.
    before = [s.exited for s in above]
    a.go_home()
    assert [s.exited for s in above] == [n + 1 for n in before]


def test_go_home_from_the_root_is_a_no_op(tmp_path):
    a = _app(tmp_path, 1)
    a.go_home()
    assert len(a.stack) == 1


def test_back_button_routes_through_go_back(tmp_path):
    """One hook, so the swipe and the keyboard can never disagree."""
    a = _app(tmp_path, 2)
    seen = []
    a.stack[-1].go_back = lambda: seen.append("back")
    a.stack[-1].handle(Button.BACK, PlayerStatus.disconnected())
    assert seen == ["back"]


def test_home_button_routes_to_go_home(tmp_path):
    a = _app(tmp_path, 3)
    a.stack[-1].handle(Button.HOME, PlayerStatus.disconnected())
    assert len(a.stack) == 1


def test_home_is_mapped_for_dev_keyboard():
    from musi.player.input import key_to_button
    assert key_to_button(pygame.K_h) is Button.HOME
