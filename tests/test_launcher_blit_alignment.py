"""Nothing may land on a transparent page at an odd x — that blit SIGBUSes.

On the device (armv7, pygame-ce 2.5.7 / SDL 2.32.4) a per-pixel-alpha source
blitted onto a per-pixel-alpha destination takes SDL's ARM SIMD blitter, which
moves 8 bytes at a time and faults on a 4-mod-8 address. Odd x plus a source
pitch that is a multiple of 8 kills the process; x86 never takes that path, so
only this invariant catches the regression here.
"""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.library.db import open_db, run_migrations
from musi.player.screens import launcher
from musi.player.screens.launcher import PAGE_H, LauncherScreen


class FakeApp:
    def __init__(self, db):
        self.db = db
        self.stack = []

    def push(self, screen):
        self.stack.append(screen)

    def sleep_remaining(self):
        return None


@pytest.fixture
def app(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    return FakeApp(conn)


class _Recorder(pygame.Surface):
    """A page surface that remembers what was blitted onto it, and where."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.landings: list[tuple[int, pygame.Surface]] = []

    def blit(self, source, dest, *args, **kwargs):
        x = dest[0] if not isinstance(dest, pygame.Rect) else dest.x
        self.landings.append((x, source))
        return super().blit(source, dest, *args, **kwargs)


def _page_landings(app, idx, subtitle, monkeypatch):
    """Build page ``idx`` with a forced subtitle; return its recorded blits."""
    screen = LauncherScreen(app)
    app.stack.append(screen)
    monkeypatch.setattr(screen, "subtitle", lambda key: subtitle)

    real_surface = pygame.Surface

    def factory(size, *args, **kwargs):
        if tuple(size) == (320, PAGE_H):
            return _Recorder(size, *args, **kwargs)
        return real_surface(size, *args, **kwargs)

    monkeypatch.setattr(launcher.pygame, "Surface", factory)
    page = screen._page(idx)
    monkeypatch.undo()
    return page.landings


# Widths of these render to a spread of odd and even values, so the centred
# blits land on both parities.
SUBTITLES = ["", "1 album", "203 albums", "12 albums", "on", "3h 04m left", "iii"]


@pytest.mark.parametrize("idx", range(len(LauncherScreen.APPS)))
@pytest.mark.parametrize("subtitle", SUBTITLES)
def test_page_blits_land_on_an_even_column(app, idx, subtitle, monkeypatch):
    landings = _page_landings(app, idx, subtitle, monkeypatch)
    assert landings, "expected the page to be composed of blits"
    for x, source in landings:
        if source.get_flags() & pygame.SRCALPHA and source.get_pitch() % 8 == 0:
            assert x % 2 == 0, (
                f"page {idx} blits a {source.get_size()} alpha surface at x={x}; "
                "an odd x SIGBUSes on the Pi"
            )
