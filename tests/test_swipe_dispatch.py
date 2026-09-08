"""The edge swipe as app.py resolves it — including everything it must NOT break."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.app import App
from musi.player.screen import Screen


class Probe(Screen):
    """Records navigation and scrolling, and can capture gestures like the
    launcher and the volume slider do."""

    def __init__(self, app, capture=False):
        super().__init__(app)
        self.capture = capture
        self.backs = 0
        self.scrolled = 0.0
        self.scroll_ends = 0
        self.taps = []

    def draw(self, surface, status):
        pass

    def on_press(self, x, y):
        return self.capture

    def go_back(self):
        self.backs += 1

    def handle_scroll(self, dy):
        self.scrolled += dy

    def handle_scroll_end(self):
        self.scroll_ends += 1

    def handle_touch(self, x, y):
        self.taps.append((x, y))
        return None


def _app(tmp_path, depth=2, capture=False):
    a = App(mpd=None, db=None, art_dir=tmp_path, lyrics_dir=tmp_path)
    for _ in range(depth):
        a.push(Probe(a, capture=capture))
    return a


def _swipe(a, x0=5, steps=((30, 0), (30, 0), (30, 0))):
    """Drive a drag through the same entry points the pygame loop uses."""
    a._begin_touch(x0, 200, 0.0)
    x = x0
    for dx, dy in steps:
        x += dx
        a._move_touch(x, 200, dx, dy)
    a._end_touch(x, 200)


def test_an_edge_swipe_goes_back(tmp_path):
    a = _app(tmp_path)
    top = a.stack[-1]
    _swipe(a)
    assert top.backs == 1


def test_the_swipe_fires_only_once_per_gesture(tmp_path):
    """Latched, so a long drag does not pop three screens."""
    a = _app(tmp_path)
    top = a.stack[-1]
    _swipe(a, steps=((30, 0),) * 8)
    assert top.backs == 1


def test_a_captured_gesture_never_goes_back(tmp_path):
    """The launcher pages horizontally and the volume slider drags — both
    capture via on_press, and must keep the whole gesture."""
    a = _app(tmp_path, capture=True)
    top = a.stack[-1]
    _swipe(a)
    assert top.backs == 0


def test_a_swipe_at_the_root_does_nothing(tmp_path):
    a = _app(tmp_path, depth=1)
    top = a.stack[-1]
    _swipe(a)
    assert top.backs == 0


def test_a_mid_screen_swipe_does_not_go_back(tmp_path):
    a = _app(tmp_path)
    top = a.stack[-1]
    _swipe(a, x0=160)
    assert top.backs == 0


def test_a_vertical_drag_scrolls_and_does_not_go_back(tmp_path):
    a = _app(tmp_path)
    top = a.stack[-1]
    _swipe(a, steps=((0, 40), (0, 40), (0, 40)))
    assert top.backs == 0
    assert top.scrolled == 120


def test_a_fired_swipe_does_not_start_momentum(tmp_path):
    """The screen is gone; coasting a list nobody is looking at wastes frames."""
    a = _app(tmp_path)
    top = a.stack[-1]
    _swipe(a)
    assert top.scroll_ends == 0


def test_a_fired_swipe_does_not_also_register_a_tap(tmp_path):
    a = _app(tmp_path)
    top = a.stack[-1]
    _swipe(a)
    assert top.taps == []


def test_a_tap_still_works(tmp_path):
    a = _app(tmp_path)
    top = a.stack[-1]
    a._begin_touch(160, 10, 0.0)
    a._end_touch(160, 10)
    assert top.taps == [(160, 10)]
