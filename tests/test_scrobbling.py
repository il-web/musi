"""Scrobbling — when a play counts, ListenBrainz's queue, ReplayGain."""
import json
import threading
import urllib.error

import pytest

from musi.library import listenbrainz as lb
from musi.player.scrobbler import Scrobbler, qualifies


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_LISTENBRAINZ_PATH", str(tmp_path / "lb.json"))
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))


# ── the rule ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("played,duration,ok", [
    (100, 200, True),       # half
    (99, 200, False),
    (240, 600, True),       # four minutes beats half of a long track
    (239, 600, False),
    (20, 25, False),        # under 30 s never counts
    (240, 0, True),         # unknown length: four minutes
])
def test_half_or_four_minutes(played, duration, ok):
    assert qualifies(played, duration) is ok


class St:
    def __init__(self, path="/m/a.flac", state="play", elapsed=0.0, duration=200.0):
        self.path, self.state, self.elapsed, self.duration = path, state, elapsed, duration
        self.title, self.artist, self.album, self.connected = "T", "A", "Al", True


def _scrobbler():
    started, listened = [], []
    s = Scrobbler(on_start=started.append,
                  on_listen=lambda m, t: listened.append((m["path"], t)))
    return s, started, listened


def _play(s, path, seconds, t0, state="play", duration=200.0):
    for i in range(seconds + 1):
        s.update(St(path, state, elapsed=i, duration=duration), now=t0 + i, wall=1000 + t0 + i)
    return t0 + seconds


def test_a_track_played_past_half_counts_when_the_next_starts():
    s, started, listened = _scrobbler()
    t = _play(s, "/m/a.flac", 110, 0)
    assert listened == []                      # still playing: not yet
    _play(s, "/m/b.flac", 1, t + 1)
    assert listened == [("/m/a.flac", 1000)]  # listened_at = when it started
    assert [m["path"] for m in started] == ["/m/a.flac", "/m/b.flac"]


def test_a_skip_does_not_count():
    s, _, listened = _scrobbler()
    t = _play(s, "/m/a.flac", 30, 0)
    _play(s, "/m/b.flac", 1, t + 1)
    assert listened == []


def test_paused_time_is_not_listening():
    s, _, listened = _scrobbler()
    t = _play(s, "/m/a.flac", 60, 0)
    t = _play(s, "/m/a.flac", 300, t + 1, state="pause")
    _play(s, "/m/b.flac", 1, t + 1)
    assert listened == []


def test_a_stalled_loop_cannot_credit_minutes_at_once():
    s, _, listened = _scrobbler()
    s.update(St("/m/a.flac"), now=0, wall=0)
    s.update(St("/m/a.flac", elapsed=1), now=500, wall=500)   # 500 s gap
    s.update(St("/m/b.flac"), now=501, wall=501)
    assert listened == []


def test_repeat_one_counts_each_time_round():
    s, _, listened = _scrobbler()
    t = _play(s, "/m/a.flac", 120, 0)
    _play(s, "/m/a.flac", 2, t + 1)            # elapsed jumped back to 0
    assert len(listened) == 1


# ── ListenBrainz queue ────────────────────────────────────────────────────────

class FakeLB:
    def __init__(self, fail=False):
        self.fail, self.requests = fail, []

    def __call__(self, req):
        if self.fail:
            raise urllib.error.URLError("offline")
        self.requests.append((req.get_method(), req.full_url,
                              req.get_header("Authorization"),
                              json.loads(req.data) if req.data else None))
        if req.full_url.endswith("/validate-token"):
            return json.dumps({"valid": True, "user_name": "ilay"}).encode()
        return b'{"status": "ok"}'


def test_validate_token_returns_the_user():
    fake = FakeLB()
    assert lb.validate_token("tok", opener=fake) == "ilay"
    assert fake.requests[0][2] == "Token tok"


def test_listens_wait_in_the_queue_until_a_flush_succeeds(monkeypatch):
    monkeypatch.setattr(lb, "flush_async", lambda: None)
    lb.save_settings("tok", "ilay")
    meta = {"title": "Up", "artist": "Band", "album": "Al", "duration": 200}
    lb.record_listen(meta, 1700000000)
    lb.record_listen(meta, 1700000300)
    assert lb.queued() == 2

    with pytest.raises(lb.ListenBrainzError):
        lb.flush(opener=FakeLB(fail=True))
    assert lb.queued() == 2                     # offline: nothing lost

    fake = FakeLB()
    assert lb.flush(opener=fake) == 2
    assert lb.queued() == 0
    body = fake.requests[0][3]
    assert body["listen_type"] == "import"
    listen = body["payload"][0]
    assert listen["listened_at"] == 1700000000
    assert listen["track_metadata"]["track_name"] == "Up"
    assert listen["track_metadata"]["release_name"] == "Al"
    assert listen["track_metadata"]["additional_info"]["duration_ms"] == 200000


def test_nothing_is_queued_without_a_token(monkeypatch):
    monkeypatch.setattr(lb, "flush_async", lambda: None)
    lb.record_listen({"title": "x"}, 1)
    assert lb.queued() == 0


# ── ReplayGain ────────────────────────────────────────────────────────────────

def test_replay_gain_sets_mpd_mode():
    from musi.player.mpd_client import MusiMPDClient

    class Sock:
        calls = []

        def ping(self):
            pass

        def replay_gain_mode(self, mode):
            self.calls.append(mode)

    c = MusiMPDClient.__new__(MusiMPDClient)
    c._connected, c._lock, c._client = True, threading.RLock(), Sock()
    c.set_replay_gain(True)
    c.set_replay_gain(False)
    assert Sock.calls == ["auto", "off"]


def test_volume_leveling_switch_writes_pref_and_tells_mpd():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    pygame.init()
    pygame.display.set_mode((320, 480))
    from musi.player import prefs
    from musi.player.screens.playback import PlaybackScreen
    prefs.reload()

    class MPD:
        calls = []

        def set_replay_gain(self, on):
            self.calls.append(on)

    class App:
        mpd, stack = MPD(), []

    scr = PlaybackScreen(App())
    scr.activate("replaygain")
    assert prefs.get("replaygain") is True and MPD.calls == [True]
    prefs.reload()
