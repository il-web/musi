"""SUB/WAVE — connect, live now-playing, song requests (library/subwave.py)."""
import os
import time
import urllib.error

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library import subwave

NP = {
    "nowPlaying": {"title": "Midnight City", "artist": "M83",
                   "album": "Hurry Up, We're Dreaming", "subsonic_id": "a1b2c3"},
    "dj": {"name": "Frequency", "station": "Night Shift FM"},
    "activeShow": None, "listeners": 3, "streamOnline": True,
    "stream": {"mount": "/stream.mp3", "format": "mp3"},
}
JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"rest"


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    from musi.library import config
    monkeypatch.setattr(config, "radio_path", lambda: tmp_path / "radio.json")
    monkeypatch.setattr(config, "art_dir", lambda: tmp_path / "art")
    subwave._state.clear()


def caddy(urls):
    """All-in-one image behind Caddy on one host."""
    def opener(url, data):
        urls.append((url, data))
        if url == "http://radio.lan/api/now-playing":
            return NP
        if url == "http://radio.lan/stream.mp3":
            return True
        if url == "http://radio.lan/api/cover/a1b2c3":
            return JPEG
        raise urllib.error.URLError("refused")
    return opener


def test_normalize():
    assert subwave.normalize(" radio.lan/ ") == "http://radio.lan"
    assert subwave.normalize("https://r.example.com:8443") == "https://r.example.com:8443"
    with pytest.raises(subwave.SubwaveError):
        subwave.normalize("   ")


def test_connect_behind_caddy():
    st = subwave.connect("radio.lan", opener=caddy([]))
    assert st["provider"] == "subwave"
    assert st["name"] == "Night Shift FM"
    assert st["url"] == "http://radio.lan/stream.mp3"
    assert st["api"] == "http://radio.lan/api"


def test_connect_bring_your_own_ports():
    def opener(url, data):
        if url == "http://10.0.0.5:7701/now-playing":
            return NP
        if url == "http://10.0.0.5:7702/stream.mp3":
            return True
        raise urllib.error.URLError("refused")
    st = subwave.connect("10.0.0.5:7700", opener=opener)
    assert st["api"] == "http://10.0.0.5:7701"
    assert st["url"] == "http://10.0.0.5:7702/stream.mp3"


def test_connect_rejects_something_else():
    with pytest.raises(subwave.SubwaveError):
        subwave.connect("radio.lan", opener=lambda u, d: {"hello": "world"})


def test_saved_station_round_trip():
    st = subwave.connect("radio.lan", opener=caddy([]))
    subwave.save(st)
    assert subwave.load() == st
    subwave.forget()
    assert subwave.load() is None


def test_live_polls_and_fetches_the_cover(monkeypatch):
    import threading

    class Sync:
        def __init__(self, target, args=(), daemon=None):
            self.t, self.a = target, args

        def start(self):
            self.t(*self.a)
    monkeypatch.setattr(threading, "Thread", Sync)
    st = subwave.connect("radio.lan", opener=caddy([]))
    first = subwave.live(st, opener=caddy([]))          # kicks the poll
    assert first["info"] is None
    snap = subwave.live(st, opener=caddy([]))
    assert snap["info"]["title"] == "Midnight City"
    assert snap["info"]["dj"] == "Frequency"
    assert snap["cover"].suffix == ".jpg" and snap["cover"].read_bytes() == JPEG
    rev = snap["rev"]
    assert subwave.live(st, opener=caddy([]))["rev"] == rev   # not due again yet


def test_request_resolves_with_the_track():
    st = {"api": "http://radio.lan/api"}
    seen = []

    def opener(url, data):
        seen.append(url)
        if url.endswith("/request"):
            return {"success": True, "requestId": "r1", "status": "pending"}
        return {"status": "resolved", "track": {"title": "Open Eye Signal",
                                                "artist": "Jon Hopkins"}}
    msg = subwave.request_and_wait(st, "something slower", opener=opener, every=0)
    assert msg == "Coming up: Jon Hopkins — Open Eye Signal"
    assert seen[-1] == "http://radio.lan/api/request/r1"


def test_request_rejected_and_rate_limited():
    st = {"api": "http://radio.lan/api"}

    def rejected(url, data):
        if url.endswith("/request"):
            return {"requestId": "r2"}
        return {"status": "rejected", "message": "nothing like that here"}
    assert "nothing like that here" in subwave.request_and_wait(st, "x", opener=rejected, every=0)

    def limited(url, data):
        raise urllib.error.HTTPError(url, 429, "slow down", {}, None)
    with pytest.raises(subwave.SubwaveError, match="too many"):
        subwave.request(st, "x", opener=limited)


# ── Radio screen ──────────────────────────────────────────────────────────────

class FakeApp:
    def __init__(self):
        self.stack = []
        self.db = None
        self.mpd = None

        class S:
            path = ""
        self.status = S()

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()


def _radio_screen(monkeypatch):
    from musi.library import radio
    from musi.player.screens.radio import RadioScreen
    monkeypatch.setattr(radio, "saved", lambda: [])
    s = RadioScreen(FakeApp())
    s.local, s.local_error = [], ""
    s._rebuild()
    return s


def test_radio_offers_connect_then_the_station_and_requests(monkeypatch):
    s = _radio_screen(monkeypatch)
    assert s.rows[0] == ("header", "SUB/WAVE")
    assert s.rows[1] == ("action", ("sw-connect", "Connect your SUB/WAVE station"))
    s.on_action("sw-connect")
    assert type(s.app.stack[-1]).__name__ == "TextEntryScreen"

    subwave.save(subwave.connect("radio.lan", opener=caddy([])))
    s._rebuild()
    assert s.rows[1][0] == "station" and s.rows[1][1]["name"] == "Night Shift FM"
    assert s.rows[2] == ("action", ("sw-request", "Request a song"))

    from musi.player.mpd_client import PlayerStatus
    st = PlayerStatus(state="stop", path="", title="", artist="", album="",
                      elapsed=0.0, duration=0.0, volume=50, shuffle=False,
                      repeat=False, queue_pos=-1, queue_len=0)
    s.draw(pygame.Surface((320, 480)), st)               # must not raise


def test_now_playing_shows_the_subwave_track_cover_and_dj(monkeypatch, tmp_path):
    from musi.library import radio
    from musi.player.screens import now_playing
    import test_now_playing_screen as npt

    st = subwave.connect("radio.lan", opener=caddy([]))
    cover = tmp_path / "c.png"
    img = pygame.Surface((40, 40))
    img.fill((200, 40, 40))
    pygame.image.save(img, str(cover))
    info = subwave.parse_now_playing(NP, st["api"])
    monkeypatch.setattr(radio, "station_for", lambda url: st)
    monkeypatch.setattr(subwave, "live",
                        lambda station: {"info": info, "cover": cover, "rev": 1})

    app = npt.FakeApp()
    app.status.path = st["url"]
    app.status.title = "M83 - Midnight City"           # the ICY title MPD sees
    app.status.artist = app.status.album = ""
    s = now_playing.NowPlayingScreen(app)
    s.on_enter()
    surf = pygame.Surface((320, 480))
    s.draw(surf, app.status)
    assert s._prev_title[0] == "Midnight City"
    assert s._prev_meta.startswith("M83")
    assert s._dj_line() == "DJ Frequency · 3 listening"
    assert s._art is not None and s._art.get_at((160, 100))[:3] == (200, 40, 40)
