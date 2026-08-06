"""theme.render truncation — only shorten text that genuinely overflows."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import theme


def _w(text, size=16, bold=False):
    return theme.font(size, bold).size(text)[0]


def test_text_that_fits_is_rendered_whole():
    """A string just under the limit must not gain an ellipsis.

    The old logic tested `text + "..."` against max_width unconditionally, so
    anything within one ellipsis-width of the limit was needlessly clipped.
    """
    text = "That's all we need because it's all we can take"
    width = _w(text)
    surf = theme.render(text, 16, theme.WHITE, max_width=width + 2)
    assert surf.get_width() >= width - 1


def test_text_exactly_at_the_limit_is_whole():
    text = "Exactly this wide"
    surf = theme.render(text, 16, theme.WHITE, max_width=_w(text))
    assert surf.get_width() >= _w(text) - 1


def test_overflowing_text_is_truncated_within_the_limit():
    text = "A considerably longer line of text than will ever fit here"
    limit = 120
    surf = theme.render(text, 16, theme.WHITE, max_width=limit)
    assert surf.get_width() <= limit
    assert surf.get_width() < _w(text)


def test_no_max_width_never_truncates():
    text = "A considerably longer line of text than will ever fit here"
    assert theme.render(text, 16, theme.WHITE).get_width() >= _w(text) - 1


def test_empty_text_is_safe():
    assert theme.render("", 16, theme.WHITE, max_width=100).get_width() == 0


def test_a_single_huge_word_still_fits_the_limit():
    surf = theme.render("A" * 200, 16, theme.WHITE, max_width=100)
    assert surf.get_width() <= 100
