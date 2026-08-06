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


def test_wrap_uses_as_many_rows_as_it_takes():
    """No row cap: a long line wraps rather than losing its tail."""
    text = " ".join(["word"] * 60)
    rows = ls._wrap(text, 15, True, 292)
    assert len(rows) > 2
    assert " ".join(rows) == text


def test_wrap_of_one_huge_word_still_returns_it():
    assert ls._wrap("A" * 200, 15, True, 292) == ["A" * 200]


# ── never sleeps ──────────────────────────────────────────────────────────────

def test_screen_never_dims_or_sleeps():
    """Reading lyrics involves no touching — the panel must stay lit."""
    assert ls.LyricsScreen.dim_after == 0
    assert ls.LyricsScreen.off_after == 0


# ── every line wraps, not just the active one ─────────────────────────────────

def test_no_line_is_ever_truncated(tmp_path, monkeypatch):
    long_line = "This is a really quite long lyric line that will not fit"
    lrc = f"[00:00.00] short\n[00:04.00] {long_line}\n[00:08.00] also short"
    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", lambda *a, **k: Lyrics(
        lines=parse_lrc(lrc), synced=True, found=True))
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    surface = pygame.Surface((320, 480))
    st = St()
    st.elapsed = 0.0                       # the long line is NOT active here
    s.draw(surface, st)
    rows = s.rows_for(1)
    assert len(rows) > 1                   # wrapped, not cut
    assert " ".join(rows) == long_line     # every word survives


def test_inactive_long_lines_wrap_too(tmp_path, monkeypatch):
    long_line = "Another extremely long line of lyrics that overflows the panel"
    lrc = f"[00:00.00] {long_line}\n[00:04.00] b"
    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", lambda *a, **k: Lyrics(
        lines=parse_lrc(lrc), synced=True, found=True))
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    st = St()
    st.elapsed = 5.0                       # line 0 inactive
    s.draw(pygame.Surface((320, 480)), st)
    assert len(s.rows_for(0)) > 1


def test_wrapped_lines_do_not_overlap(tmp_path, monkeypatch):
    lrc = ("[00:00.00] A really long first line that has to wrap somewhere\n"
           "[00:04.00] short\n"
           "[00:08.00] Another long line that also needs to wrap onto rows")
    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", lambda *a, **k: Lyrics(
        lines=parse_lrc(lrc), synced=True, found=True))
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    st = St()
    st.elapsed = 5.0
    s.draw(pygame.Surface((320, 480)), st)
    spans = [(y - h / 2, y + h / 2) for _i, y, h in s._laid]
    for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
        assert a1 <= b0 + 1, "lines overlap vertically"


def test_bigger_text_than_before(tmp_path, monkeypatch):
    assert ls.ACTIVE_SIZE >= 17
    assert ls.LINE_SIZE >= 15


# ── follows a track change ────────────────────────────────────────────────────

class St2(St):
    title = "Second"
    artist = "Other"
    album = "Album2"
    path = "/m/t2.mp3"
    duration = 111.0


def test_track_change_reloads_for_the_new_song(tmp_path, monkeypatch):
    seen = []

    def spy(lyrics_dir, artist, title, album, duration, **kw):
        seen.append(title)
        return Lyrics(lines=parse_lrc(_LRC), synced=True, found=True)

    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", spy)
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    assert seen == ["Song"]

    s.draw(pygame.Surface((320, 480)), St2())   # song changed under us
    s.join()
    assert seen == ["Song", "Second"]
    assert s.title == "Second"


def test_same_track_does_not_refetch(tmp_path, monkeypatch):
    seen = []

    def spy(lyrics_dir, artist, title, album, duration, **kw):
        seen.append(title)
        return Lyrics(lines=parse_lrc(_LRC), synced=True, found=True)

    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", spy)
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()
    for _ in range(5):
        s.draw(pygame.Surface((320, 480)), St())
    s.join()
    assert seen == ["Song"]


def test_stopping_playback_does_not_clear_the_lyrics(tmp_path, monkeypatch):
    """An empty path between tracks must not blank the screen."""
    monkeypatch.setattr(ls.lyrics_lib, "get_lyrics", lambda *a, **k: Lyrics(
        lines=parse_lrc(_LRC), synced=True, found=True))
    s = ls.LyricsScreen(FakeApp(tmp_path), St())
    s.on_enter()
    s.join()

    class Empty(St):
        path = ""

    s.draw(pygame.Surface((320, 480)), Empty())
    assert s.result.found is True
    assert s.title == "Song"
