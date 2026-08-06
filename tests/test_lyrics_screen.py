"""LyricsScreen — loads on demand for the current track, follows playback."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.library.lyrics import Lyrics, parse_lrc
from musi.player.screens import lyrics as ls

_LRC = "\n".join(f"[00:{s:02d}.00] line {i}" for i, s in enumerate(range(0, 40, 4)))


class FakeMPD:
    def __init__(self):
        self.seeks = []

    def seek(self, seconds):
        self.seeks.append(seconds)


class FakeApp:
    db = None

    def __init__(self, tmp_path):
        self.stack = [None, None]
        self.mpd = FakeMPD()
        self.lyrics_dir = tmp_path
        self.polled = 0

    def request_poll(self):
        self.polled += 1

    def toggle_play(self):
        pass

    def push(self, s):
        self.stack.append(s)


class St:
    title = "Song"
    artist = "Band"
    album = "Album"
    path = "/m/t1.mp3"
    state = "play"
    connected = True
    duration = 200.0
    progress = 0.0
    elapsed = 0.0


def _screen(tmp_path, monkeypatch, result=None):
    if result is not None:
        monkeypatch.setattr(ls.lyrics_lib, "get_lyrics",
                            lambda *a, **k: result)
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    return s


def _synced() -> Lyrics:
    lines = parse_lrc(_LRC)
    return Lyrics(lines=lines, synced=True, found=True)


# ── loading ───────────────────────────────────────────────────────────────────

def test_starts_loading_on_enter(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, _synced())
    s.on_enter()
    s.join()
    assert s.loading is False
    assert s.result.found is True


def test_only_requests_the_track_it_was_opened_for(tmp_path, monkeypatch):
    seen = []

    def spy(lyrics_dir, artist, title, album, duration, **kw):
        seen.append((artist, title, album, duration))
        return _synced()

    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", spy)
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    assert seen == [("Band", "Song", "Album", 200.0)]


def test_animates_only_while_loading(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, _synced())
    assert s.animates is False
    s.loading = True
    assert s.animates is True


def test_a_miss_is_reported(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, Lyrics(found=False))
    s.on_enter()
    s.join()
    assert "No lyrics" in s.message()


def test_an_instrumental_says_so(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, Lyrics(found=False, instrumental=True))
    s.on_enter()
    s.join()
    assert "nstrumental" in s.message()


def test_a_network_error_is_shown(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, Lyrics(found=False, error="no route"))
    s.on_enter()
    s.join()
    assert "no route" in s.message()


# ── following playback ────────────────────────────────────────────────────────

def test_active_line_follows_elapsed(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, _synced())
    s.on_enter()
    s.join()
    st = St()
    st.elapsed = 9.0                      # lines at 0,4,8,12...
    assert s.active_at(st) == 2


def test_tap_on_a_line_seeks_there(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, _synced())
    s.on_enter()
    s.join()
    surface = pygame.Surface((320, 480))
    st = St()
    s.draw(surface, st)                   # lays the lines out
    y = s.line_y(3)
    assert y is not None
    s.handle_touch(160, y)
    assert s.app.mpd.seeks == [s.result.lines[3][0]]


def test_tap_does_not_seek_for_plain_lyrics(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch,
                Lyrics(plain="a\nb\nc", synced=False, found=True))
    s.on_enter()
    s.join()
    surface = pygame.Surface((320, 480))
    s.draw(surface, St())
    s.handle_touch(160, 240)
    assert s.app.mpd.seeks == []


def test_retry_forces_a_refetch(tmp_path, monkeypatch):
    calls = []

    def spy(*a, force=False, **k):
        calls.append(force)
        return Lyrics(found=False)

    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", spy)
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    s.handle_touch(ls.RETRY_RECT.centerx, ls.RETRY_RECT.centery)
    s.join()
    assert calls == [False, True]


# ── draw ──────────────────────────────────────────────────────────────────────

def test_draw_runs_in_every_state(tmp_path, monkeypatch):
    surface = pygame.Surface((320, 480))
    for res in (_synced(),
                Lyrics(plain="one\ntwo", synced=False, found=True),
                Lyrics(found=False),
                Lyrics(found=False, instrumental=True),
                Lyrics(found=False, error="boom")):
        s = _screen(tmp_path, monkeypatch, res)
        s.on_enter()
        s.join()
        s.draw(surface, St())


def test_draw_while_loading(tmp_path, monkeypatch):
    s = _screen(tmp_path, monkeypatch, _synced())
    s.loading = True
    s.draw(pygame.Surface((320, 480)), St())


# ── wrapping ──────────────────────────────────────────────────────────────────

def test_short_lines_are_not_wrapped():
    assert ls._wrap("short", 15, True, 292) == ["short"]


def test_long_active_lines_wrap_instead_of_truncating():
    text = "One thing I never see the same when your 'round"
    rows = ls._wrap(text, 15, True, 292)
    assert len(rows) == 2
    assert " ".join(rows) == text          # every word survives


def test_wrap_never_exceeds_max_rows():
    text = " ".join(["word"] * 60)
    assert len(ls._wrap(text, 15, True, 292)) == 2


def test_wrap_of_one_huge_word_still_returns_it():
    assert ls._wrap("A" * 200, 15, True, 292) == ["A" * 200]
