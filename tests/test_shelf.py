"""Shelf — horizontal art strip scrolling."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.widgets import Shelf


def test_pitch_is_item_plus_gap():
    s = Shelf(item_w=92, gap=10)
    assert s.pitch == 102


def test_no_scroll_when_everything_fits():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(3)                      # 3 * 102 = 306 <= 320
    assert s.max_offset == 0


def test_scrolls_when_it_overflows():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(6)                      # 612 - 320
    assert s.max_offset == 292


def test_drag_moves_content_with_the_finger():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(6)
    s.start_touch()
    s.drag_by(-50)                      # finger left = content left = offset up
    assert s._k.offset == 50


def test_drag_is_clamped_at_both_ends():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(6)
    s.start_touch()
    s.drag_by(500)
    assert s._k.offset == 0
    s.drag_by(-5000)
    assert s._k.offset == s.max_offset


def test_index_at_maps_x_to_an_item():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(6)
    assert s.index_at(0) == 0
    assert s.index_at(101) == 0
    assert s.index_at(102) == 1


def test_index_at_accounts_for_scroll():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(6)
    s.start_touch()
    s.drag_by(-102)                     # scrolled one full item
    assert s.index_at(0) == 1


def test_set_count_reset_returns_to_the_start():
    s = Shelf(item_w=92, gap=10, view_w=320)
    s.set_count(6)
    s.start_touch()
    s.drag_by(-200)
    s.set_count(6, reset=True)
    assert s._k.offset == 0
