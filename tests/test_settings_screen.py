"""Settings — grouped sections that scroll."""
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens import settings


class App:
    db = None

    def __init__(self):
        self.stack = []

    def push(self, s):
        self.stack.append(s)


def test_every_row_is_in_exactly_one_group():
    names = [n for _, ns in settings.GROUPS for n in ns]
    assert sorted(names) == sorted(set(names)) == sorted(settings.MENU)


def test_rows_below_the_fold_are_reachable_and_open_the_right_screen():
    app = App()
    scr = settings.SettingsScreen(app)
    app.stack.append(scr)
    scr.handle_scroll(-1000)                      # drag all the way up
    assert scr._scroll == scr._max_scroll > 0
    power = settings.MENU.index("Power")
    y = settings._TOP + scr._rows[power] - int(scr._scroll) + settings.ROW_H // 2
    scr.handle_touch(160, y)
    time.sleep(0.15)
    scr._tap.update()
    assert app.stack[-1].__class__.__name__ == "PowerScreen"


def test_keyboard_selection_scrolls_into_view():
    scr = settings.SettingsScreen(App())
    from musi.player.input import Button
    for _ in range(len(settings.MENU) - 1):
        scr.handle(Button.DOWN, None)
    assert scr._scroll > 0
