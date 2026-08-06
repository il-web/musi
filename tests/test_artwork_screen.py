"""Artwork screen — counts missing art, fetches on a worker, reports results."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.player.screens import artwork as art_screen


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
    db = object()

    def __init__(self, tmp_path):
        self.stack = [None, None]
        self._art = tmp_path

    @property
    def art_dir(self):
        return self._art

    def toggle_play(self):
        pass

    def push(self, s):
        self.stack.append(s)


@pytest.fixture
def screen(tmp_path, monkeypatch):
    monkeypatch.setattr(art_screen.art_fetch, "albums_missing_art",
                        lambda conn, art_dir=None: [
                            {"id": 1, "artist": "A", "album": "X",
                             "album_key": "A::X"},
                            {"id": 2, "artist": "B", "album": "Y",
                             "album_key": "B::Y"},
                        ])
    s = art_screen.ArtworkScreen(FakeApp(tmp_path))
    s.on_enter()
    return s


def test_counts_missing_albums_on_enter(screen):
    assert screen.missing == 2


def test_idle_summary_names_the_count(screen):
    assert "2 albums" in screen.summary()


def test_summary_when_nothing_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(art_screen.art_fetch, "albums_missing_art",
                        lambda conn, art_dir=None: [])
    s = art_screen.ArtworkScreen(FakeApp(tmp_path))
    s.on_enter()
    assert s.missing == 0
    assert "All albums have artwork" in s.summary()


def test_fetch_button_starts_a_worker(screen, monkeypatch):
    calls = []
    monkeypatch.setattr(art_screen.art_fetch, "fetch_missing",
                        lambda *a, **k: calls.append(k) or (2, 2))
    screen.handle_touch(art_screen.FETCH_RECT.centerx,
                        art_screen.FETCH_RECT.centery)
    screen.join()                       # deterministic: wait for the worker
    assert screen.done == (2, 2)
    assert screen.running is False


def test_fetch_reports_its_result(screen, monkeypatch):
    monkeypatch.setattr(art_screen.art_fetch, "fetch_missing",
                        lambda *a, **k: (1, 2))
    screen._start()
    screen.join()
    assert "1 of 2" in screen.summary()


def test_a_failing_fetch_surfaces_the_error(screen, monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(art_screen.art_fetch, "fetch_missing", boom)
    screen._start()
    screen.join()
    assert screen.running is False
    assert "network down" in screen.summary()


def test_second_tap_while_running_is_ignored(screen, monkeypatch):
    started = []
    monkeypatch.setattr(art_screen.art_fetch, "fetch_missing",
                        lambda *a, **k: started.append(1) or (0, 0))
    screen.running = True               # pretend a worker is live
    screen.handle_touch(art_screen.FETCH_RECT.centerx,
                        art_screen.FETCH_RECT.centery)
    assert started == []


def test_nothing_to_do_does_not_start_a_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(art_screen.art_fetch, "albums_missing_art",
                        lambda conn, art_dir=None: [])
    started = []
    monkeypatch.setattr(art_screen.art_fetch, "fetch_missing",
                        lambda *a, **k: started.append(1) or (0, 0))
    s = art_screen.ArtworkScreen(FakeApp(tmp_path))
    s.on_enter()
    s.handle_touch(art_screen.FETCH_RECT.centerx, art_screen.FETCH_RECT.centery)
    assert started == []


def test_screen_animates_only_while_fetching(screen):
    assert screen.animates is False
    screen.running = True
    assert screen.animates is True


def test_draw_runs_idle_and_running(screen):
    surface = pygame.Surface((320, 480))
    screen.draw(surface, FakeStatus())
    screen.running = True
    screen.progress = (1, 2, "A — X")
    screen.draw(surface, FakeStatus())
