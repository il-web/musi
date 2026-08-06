"""Carousel gesture/animation logic — deterministic via injected clock."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.widgets import Carousel


def _drag(car, total_dx, *, t0=0.0, dt=0.02, steps=5):
    """Drag total_dx px over `steps` samples, returning the final timestamp."""
    car.start_touch(now=t0)
    t = t0
    for _ in range(steps):
        t += dt
        car.drag_by(total_dx / steps, now=t)
    return t


def test_starts_on_first_page():
    car = Carousel(4)
    assert car.index == 0
    assert car.drag_px == 0.0
    assert car.visible_pages() == [(0, 0)]


def test_drag_shows_incoming_neighbour():
    car = Carousel(4)
    _drag(car, -60)
    assert car.drag_px == pytest.approx(-60)
    # current page shifted left, next page waiting off the right edge
    assert car.visible_pages() == [(0, -60), (1, 260)]


def test_short_slow_drag_snaps_back():
    car = Carousel(4)
    t = _drag(car, -40, dt=0.2)          # slow: 40px over 1.0s = 40px/s
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S)
    assert car.index == 0
    assert car.drag_px == 0.0


def test_drag_past_half_page_advances():
    car = Carousel(4)
    t = _drag(car, -200, dt=0.2)         # slow but past 160px
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S)
    assert car.index == 1
    assert car.drag_px == 0.0


def test_fast_flick_advances_without_crossing_half():
    car = Carousel(4)
    t = _drag(car, -40)                  # 40px over 0.1s = 400px/s
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S)
    assert car.index == 1


def test_wraps_backwards_from_first_page():
    car = Carousel(4)
    t = _drag(car, 200, dt=0.2)
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S)
    assert car.index == 3


def test_wraps_forwards_from_last_page():
    car = Carousel(4)
    car.index = 3
    t = _drag(car, -200, dt=0.2)
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S)
    assert car.index == 0


def test_update_reports_motion_until_snap_completes():
    car = Carousel(4)
    t = _drag(car, -200, dt=0.2)
    car.end_touch(now=t)
    assert car.update(now=t + Carousel.SNAP_S / 2) is True
    assert car.animating is True
    assert car.update(now=t + Carousel.SNAP_S) is False
    assert car.animating is False


def test_idle_update_is_false():
    car = Carousel(4)
    assert car.update(now=1.0) is False


def test_touch_during_snap_stops_the_animation():
    car = Carousel(4)
    t = _drag(car, -200, dt=0.2)
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S / 2)
    car.start_touch(now=t + Carousel.SNAP_S / 2)
    assert car.animating is False


def test_single_page_carousel_never_advances():
    car = Carousel(1)
    t = _drag(car, -300, dt=0.2)
    car.end_touch(now=t)
    car.update(now=t + Carousel.SNAP_S)
    assert car.index == 0
    assert car.visible_pages() == [(0, 0)]
