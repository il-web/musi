"""Sleep app — picker sets and cancels the timer, countdown formatting."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens import sleep as sleep_mod


class FakeStatus:
    title = ""
    artist = ""
    album = ""
    path = ""
    state = "stop"
    connected = True
    duration = 0.0
    progress = 0.0


class FakeApp:
    db = None

    def __init__(self):
        self.stack = []
        self.timer = "unset"
        self.remaining = None

    def set_sleep_timer(self, minutes):
        self.timer = minutes

    def sleep_remaining(self):
        return self.remaining

    def push(self, screen):
        self.stack.append(screen)

    def toggle_play(self):
        pass


def test_options():
    assert sleep_mod.SleepScreen.OPTIONS == [
        ("Off", None), ("15 min", 15), ("30 min", 30),
        ("60 min", 60), ("90 min", 90),
    ]


def test_format_remaining_off():
    assert sleep_mod.format_remaining(None) == "Off"


def test_format_remaining_rounds_up():
    assert sleep_mod.format_remaining(61) == "2 min left"
    assert sleep_mod.format_remaining(1) == "1 min left"


def test_tapping_an_option_arms_the_timer():
    app = FakeApp()
    s = sleep_mod.SleepScreen(app)
    s.handle_touch(160, sleep_mod.row_y(2) + 10)   # "30 min"
    while s._tap.pending:                          # tap is deferred by PendingTap
        s._tap._t = 0.0
        s._tap.update()
    assert app.timer == 30


def test_tapping_off_cancels():
    app = FakeApp()
    app.timer = 30
    s = sleep_mod.SleepScreen(app)
    s.handle_touch(160, sleep_mod.row_y(0) + 10)
    while s._tap.pending:
        s._tap._t = 0.0
        s._tap.update()
    assert app.timer is None


def test_draw_shows_the_countdown():
    app = FakeApp()
    app.remaining = 2400.0
    s = sleep_mod.SleepScreen(app)
    surface = pygame.Surface((320, 480))
    s.draw(surface, FakeStatus())
    assert s._status_text == "41 min left"


def test_draw_with_no_timer():
    app = FakeApp()
    s = sleep_mod.SleepScreen(app)
    surface = pygame.Surface((320, 480))
    s.draw(surface, FakeStatus())
    assert s._status_text == "Off"
