"""The back-swipe resolver — a pure decision, tested without pygame."""
import pytest

from musi.player.gestures import EDGE_W, SWIPE_MIN_PX, resolve_edge_swipe


def test_swipe_from_the_left_edge_fires():
    assert resolve_edge_swipe(5, 100, 0) is True


def test_a_start_outside_the_edge_zone_never_fires():
    """Mid-screen drags belong to whatever the screen is doing."""
    assert resolve_edge_swipe(EDGE_W + 1, 100, 0) is False


def test_the_edge_zone_is_inclusive():
    assert resolve_edge_swipe(EDGE_W, 100, 0) is True


def test_travel_below_the_minimum_does_not_fire():
    assert resolve_edge_swipe(5, SWIPE_MIN_PX - 1, 0) is False


def test_travel_exactly_at_the_minimum_fires():
    assert resolve_edge_swipe(5, SWIPE_MIN_PX, 0) is True


def test_a_leftward_drag_never_fires():
    """Back is right-going only; leftward is free for anything else."""
    assert resolve_edge_swipe(5, -100, 0) is False


@pytest.mark.parametrize("dy", [50, -50])
def test_a_mostly_vertical_drag_does_not_fire(dy):
    """60 horizontal against 50 vertical is a scroll that drifted, not a swipe.
    Sign of dy must not matter — up and down are equally disqualifying."""
    assert resolve_edge_swipe(5, 60, dy) is False


@pytest.mark.parametrize("dy", [50, -50])
def test_a_clearly_horizontal_drag_fires_despite_drift(dy):
    assert resolve_edge_swipe(5, 100, dy) is True
