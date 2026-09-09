"""Crossfade — the pref, the MPD command, and the Playback screen that joins them."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import threading

import pytest

from musi.player import prefs
from musi.player.mpd_client import MusiMPDClient


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    prefs.reload()
    yield
    prefs.reload()


class FakeCrossfadeClient:
    def __init__(self):
        self.calls = []

    def ping(self):
        pass

    def crossfade(self, seconds):
        self.calls.append(seconds)


def _client():
    c = MusiMPDClient.__new__(MusiMPDClient)
    c._connected = True
    c._lock = threading.RLock()
    c._client = FakeCrossfadeClient()
    return c


# ── the pref ──────────────────────────────────────────────────────────────────

def test_crossfade_defaults_to_off():
    """Off is the safe default: crossfade cuts into the start and end of every
    track, which is wrong for anything with a deliberate intro."""
    assert prefs.get("crossfade") is False


def test_crossfade_pref_round_trips():
    prefs.set("crossfade", True)
    assert prefs.get("crossfade") is True


# ── the MPD command ───────────────────────────────────────────────────────────

def test_set_crossfade_sends_seconds():
    c = _client()
    c.set_crossfade(2)
    assert c._client.calls == [2]


def test_set_crossfade_zero_turns_it_off():
    """MPD has no separate off switch — zero seconds is off."""
    c = _client()
    c.set_crossfade(0)
    assert c._client.calls == [0]


# ── the Playback screen ───────────────────────────────────────────────────────

class FakeApp:
    def __init__(self, mpd):
        self.mpd = mpd
        self.stack = []
        self.toggled = 0

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        self.toggled += 1


def _screen():
    from musi.player.screens.playback import OPTIONS, PlaybackScreen
    app = FakeApp(_client())
    s = PlaybackScreen(app)
    app.stack.append(s)
    return s, app, OPTIONS


def _tap_option(screen, index):
    """Tap option ``index`` and let PendingTap's deferred action fire.

    PendingTap holds the action for 0.12 s so the pressed row flashes, so the
    wait is real — same idiom as tests/test_customization_screen.py."""
    import time

    from musi.player.screens import playback
    r = playback.row_rect(index)
    screen.handle_touch(r.centerx, r.centery)
    time.sleep(0.15)
    screen._tap.update()


def test_turning_crossfade_on_writes_the_pref_and_tells_mpd(monkeypatch):
    s, app, OPTIONS = _screen()
    on = next(i for i, (v, _) in enumerate(OPTIONS) if v is True)
    _tap_option(s, on)
    assert prefs.get("crossfade") is True
    assert app.mpd._client.calls == [2]


def test_turning_crossfade_off_sends_zero():
    s, app, OPTIONS = _screen()
    prefs.set("crossfade", True)
    off = next(i for i, (v, _) in enumerate(OPTIONS) if v is False)
    _tap_option(s, off)
    assert prefs.get("crossfade") is False
    assert app.mpd._client.calls == [0]


def test_the_screen_draws_in_both_states():
    s, _, _ = _screen()
    surf = pygame.Surface((320, 480))
    from musi.player.mpd_client import PlayerStatus
    for value in (False, True):
        prefs.set("crossfade", value)
        s.draw(surf, PlayerStatus.disconnected())


# ── Settings wiring ───────────────────────────────────────────────────────────

def test_settings_lists_playback():
    from musi.player.screens.settings import MENU
    assert "Playback" in MENU


def test_settings_menu_icons_and_openers_stay_aligned():
    """MENU, _draw_icon's index chain and _open's index chain are three
    parallel index-keyed structures. Nothing else catches a mismatch, so
    inserting a row silently puts the wrong icon on every row below it."""
    import inspect

    from musi.player.screens import settings

    icon_src = inspect.getsource(settings._draw_icon)
    open_src = inspect.getsource(settings.SettingsScreen._open)
    for i in range(len(settings.MENU)):
        assert f"index == {i}" in icon_src, f"no icon branch for MENU[{i}]"
        assert f"_sel == {i}" in open_src, f"no opener branch for MENU[{i}]"


def test_playback_row_opens_the_playback_screen():
    from musi.player.screens.playback import PlaybackScreen
    from musi.player.screens.settings import MENU, SettingsScreen

    app = FakeApp(_client())
    s = SettingsScreen(app)
    app.stack.append(s)
    s._sel = MENU.index("Playback")
    s._open()
    assert isinstance(app.stack[-1], PlaybackScreen)
