"""On-screen keyboard — big keys, no dead zones, commit on release."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import keyboard
from musi.player.keyboard import HEIGHT, Keyboard

TOP = 480 - HEIGHT


def _center(kb, value):
    for cell, _rect, _label, v in kb._keys():
        if v == value:
            return cell.center
    raise AssertionError(value)


def test_keys_are_bigger_than_before():
    kb = Keyboard(TOP)
    for cell, rect, _l, v in kb._keys():
        assert rect.height >= 40
        assert rect.width >= 28


def test_every_pixel_of_every_layer_hits_a_key():
    kb = Keyboard(TOP)
    for layer in range(3):
        kb.layer = layer
        for y in range(TOP, TOP + HEIGHT, 3):
            for x in range(0, 320, 3):
                assert kb._hit(x, y) is not None, (layer, x, y)


def test_short_row_margins_count_toward_the_end_keys():
    kb = Keyboard(TOP)
    row1 = TOP + keyboard.ROW_H + 10
    assert kb.key_at(2, row1) == "a"
    assert kb.key_at(318, row1) == "l"


def test_a_tap_types_the_key():
    kb = Keyboard(TOP)
    assert kb.key_at(*_center(kb, "q")) == "q"
    assert kb.key_at(*_center(kb, "SPACE")) == "SPACE"
    assert kb.key_at(*_center(kb, "ENTER")) == "ENTER"


def test_release_commits_the_key_under_the_finger():
    kb = Keyboard(TOP)
    kb.press(*_center(kb, "e"))
    assert kb._down == "e"
    kb.drag(*_center(kb, "r"))
    assert kb._down == "r"
    assert kb.release(*_center(kb, "r")) == "r"
    assert kb._down is None


def test_a_finger_slightly_above_the_top_row_still_types():
    kb = Keyboard(TOP)
    x, _ = _center(kb, "t")
    kb.press(x, TOP + 5)
    assert kb.release(x, TOP - 10) == "t"


def test_sliding_far_off_cancels():
    kb = Keyboard(TOP)
    kb.press(*_center(kb, "t"))
    assert kb.release(160, TOP - 100) is None


def test_shift_is_one_shot_through_press_release():
    kb = Keyboard(TOP)
    kb.press(*_center(kb, "SHIFT"))
    assert kb.release(*_center(kb, "SHIFT")) is None
    kb.press(*_center(kb, "A"))
    assert kb.release(*_center(kb, "A")) == "A"
    assert kb.shift is False


def test_draws_with_a_held_key_bubble():
    kb = Keyboard(TOP)
    surf = pygame.Surface((320, 480))
    for value in ("q", "p", "SPACE"):
        kb.press(*_center(kb, value))
        kb.draw(surf)                      # bubble clamps inside the screen
    kb.cancel()
    kb.draw(surf)


def test_screens_capture_keyboard_gestures():
    """A captured gesture skips the tap slop, so a sliding press still types."""
    from musi.player.screens.text_entry import KB_TOP, TextEntryScreen

    class App:
        stack = []

    s = TextEntryScreen(App(), "Name", on_commit=lambda t: None)
    x, y = _center(Keyboard(KB_TOP), "h")
    assert s.on_press(x, y) is True
    s.on_drag(x + 6, y + 9)
    s.on_release(x + 6, y + 9)
    assert s._text == "h"
    assert s.on_press(160, 100) is False      # above the keyboard: not ours
