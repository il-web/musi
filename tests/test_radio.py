"""Internet radio — directories, tuning, saved stations, the player side.

No network: FakeNet answers the TuneIn / Radio Browser URLs the code builds,
with replies shaped like the real ones (captured from both services).
"""
import json
import os
import urllib.parse

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library import radio, remote


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_RADIO_PATH", str(tmp_path / "radio.json"))
    monkeypatch.setenv("MUSI_ART_DIR", str(tmp_path / "art"))
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    radio._saved_cache = None
    radio._playing.clear()
    yield
    radio._saved_cache = None


GLGLZ = {"element": "outline", "type": "audio", "item": "station", "text": "GLGLZ",
         "guide_id": "s68320", "subtext": "Music is GLGLZ",
         "image": "http://cdn-profiles.tunein.com/s68320/images/logoq.jpg?t=1"}
SHOW = {"element": "outline", "type": "link", "item": "show", "text": "Calcalist",
        "guide_id": "p1143779"}


class FakeNet:
    def __init__(self, tunein_down=False, tunein_empty=False):
        self.tunein_down, self.tunein_empty = tunein_down, tunein_empty
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if "radiotime" in u.netloc:
            if self.tunein_down:
                raise radio.RadioError("down")
            if u.path.endswith("Search.ashx"):
                body = [] if self.tunein_empty else [GLGLZ, SHOW]
                return json.dumps({"head": {"status": "200"}, "body": body}).encode()
            if u.path.endswith("Browse.ashx"):
                return json.dumps({"head": {"title": "Local Radio"}, "body": [
                    {"element": "outline", "text": "Stations", "children": [GLGLZ]}]}).encode()
            if u.path.endswith("Tune.ashx"):
                assert q["id"] == "s68320"
                return json.dumps({"body": [
                    {"element": "audio", "url": "https://glz/backup", "reliability": 57},
                    {"element": "audio", "url": "http://glz/glglz_mp3", "reliability": 99},
                ]}).encode()
        if "radio-browser" in u.netloc:
            return json.dumps([{"stationuuid": "uuid-1", "name": " Galgalatz ",
                                "url_resolved": "https://glz/rb", "favicon": "",
                                "country": "Israel", "tags": "pop,hits"}]).encode()
        if url.endswith(".pls"):
            return b"[playlist]\nFile1=http://real/stream\nTitle1=x\n"
        raise AssertionError(url)


# ── directories ───────────────────────────────────────────────────────────────

def test_tunein_search_keeps_stations_and_drops_shows():
    found = radio.tunein_search("glglz", opener=FakeNet())
    assert [s["name"] for s in found] == ["GLGLZ"]
    st = found[0]
    assert st["provider"] == "tunein" and st["id"] == "s68320"
    assert "/logod." in st["image"]                 # the 300 px logo, not 145


def test_local_radio_flattens_the_outline():
    assert [s["id"] for s in radio.tunein_local(opener=FakeNet())] == ["s68320"]


@pytest.mark.parametrize("net", [FakeNet(tunein_down=True), FakeNet(tunein_empty=True)])
def test_search_falls_back_to_radio_browser(net):
    found, source = radio.search("galgalatz", opener=net)
    assert source == "rb"
    assert found[0]["name"] == "Galgalatz" and found[0]["url"] == "https://glz/rb"
    assert found[0]["subtext"] == "Israel, pop"


def test_tuning_picks_the_most_reliable_stream():
    st = radio.tunein_search("glglz", opener=FakeNet())[0]
    assert radio.stream_url(st, opener=FakeNet()) == "http://glz/glglz_mp3"


def test_tuning_falls_back_to_the_saved_stream():
    st = {"provider": "tunein", "id": "s68320", "url": "http://saved/stream"}
    assert radio.stream_url(st, opener=FakeNet(tunein_down=True)) == "http://saved/stream"


def test_playlist_files_are_unwrapped():
    st = {"provider": "rb", "id": "x", "url": "http://host/live.pls"}
    assert radio.stream_url(st, opener=FakeNet()) == "http://real/stream"


def test_no_stream_at_all_is_an_error():
    with pytest.raises(radio.RadioError):
        radio.stream_url({"provider": "tunein", "id": "s1", "url": ""},
                         opener=FakeNet(tunein_down=True))


# ── saved stations ────────────────────────────────────────────────────────────

def test_saving_round_trips_and_newest_goes_first():
    a = {"provider": "tunein", "id": "s1", "name": "A"}
    b = {"provider": "tunein", "id": "s2", "name": "B"}
    assert radio.toggle_saved(a) is True
    assert radio.toggle_saved(b) is True
    assert [s["id"] for s in radio.saved()] == ["s2", "s1"]
    radio._saved_cache = None                       # really on disk?
    assert [s["id"] for s in radio.saved()] == ["s2", "s1"]
    assert radio.toggle_saved(a) is False
    assert not radio.is_saved(a)


def test_saved_list_is_read_from_disk_once(monkeypatch):
    radio.toggle_saved({"provider": "tunein", "id": "s1"})
    radio._saved_cache = None
    radio.saved()
    monkeypatch.setattr(radio.Path, "read_text",
                        lambda *a, **k: pytest.fail("render loop hit the disk"))
    for _ in range(3):
        radio.is_saved({"provider": "tunein", "id": "s1"})


def test_the_station_on_air_survives_a_restart():
    st = {"provider": "tunein", "id": "s68320", "name": "GLGLZ"}
    radio.note_playing("http://glz/glglz_mp3", st)
    radio._playing.clear()                          # a fresh process
    assert radio.station_for("http://glz/glglz_mp3")["name"] == "GLGLZ"
    assert radio.station_for("http://other") is None


def test_radio_and_server_streams_are_told_apart():
    assert remote.kind("http://glz/glglz_mp3") == "radio"
    assert remote.kind(remote.stream_url("abc")) == "server"
    assert remote.kind("/home/musi/music/a.flac") == "local"


# ── player side ───────────────────────────────────────────────────────────────

class Status:
    def __init__(self, path, title="", state="play"):
        self.path, self.title, self.state = path, title, state
        self.artist, self.album, self.connected = "", "", True
        self.duration, self.progress, self.elapsed = 0.0, 0.0, 12.0
        self.volume, self.shuffle, self.repeat = 50, False, False


class MPD:
    def __init__(self):
        self.played = []

    def play_paths(self, paths):
        self.played.append(list(paths))

    def is_favorite(self, p):
        return False


class App:
    db = None
    lyrics_dir = None

    def __init__(self, path="http://glz/glglz_mp3"):
        self.stack, self.mpd, self.status = [], MPD(), Status(path)

    def push(self, s):
        self.stack.append(s)

    def request_poll(self):
        pass

    def toggle_play(self):
        pass


def _sync_threads(monkeypatch):
    """Run radio_play's worker inline."""
    from musi.player import radio_play

    class Inline:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(radio_play.threading, "Thread", Inline)


def test_playing_a_station_tunes_then_hands_mpd_the_stream(monkeypatch):
    from musi.player import radio_play
    _sync_threads(monkeypatch)
    monkeypatch.setattr(radio, "stream_url", lambda st: "http://glz/glglz_mp3")
    app, result = App(), []
    st = {"provider": "tunein", "id": "s68320", "name": "GLGLZ"}
    radio_play.play_station(app, st, on_done=result.append)
    assert app.mpd.played == [["http://glz/glglz_mp3"]] and result == [None]
    assert radio.station_for("http://glz/glglz_mp3")["name"] == "GLGLZ"


def test_next_and_previous_walk_the_saved_stations(monkeypatch):
    from musi.player import radio_play
    _sync_threads(monkeypatch)
    for i in (3, 2, 1):
        radio.toggle_saved({"provider": "tunein", "id": f"s{i}", "name": f"S{i}"})
    tuned = []
    monkeypatch.setattr(radio, "stream_url", lambda st: tuned.append(st["id"]) or f"http://{st['id']}")
    app = App("http://s1")
    radio.note_playing("http://s1", radio.saved()[0])
    assert radio_play.step(app, +1)
    assert radio_play.step(app, -1)
    assert tuned == ["s2", "s3"]                    # s1 → next s2; s1 → prev wraps to s3


def test_now_playing_shows_live_and_heart_saves_the_station(monkeypatch):
    from musi.player.screens import now_playing
    st = {"provider": "tunein", "id": "s68320", "name": "GLGLZ", "image": ""}
    radio.note_playing("http://glz/glglz_mp3", st)
    app = App()
    scr = now_playing.NowPlayingScreen(app)
    app.stack.append(scr)
    drawn = []
    monkeypatch.setattr(now_playing, "_draw_live", lambda *a: drawn.append(a))
    bars = []
    monkeypatch.setattr(now_playing, "_draw_bar", lambda *a: bars.append(a))
    scr.draw(pygame.Surface((320, 480)), app.status)
    assert drawn and not bars                       # LIVE, no progress bar
    scr._toggle_favorite()
    assert radio.is_saved(st)
    scr._open_lyrics()
    assert app.stack == [scr]                       # no lyrics for radio


def test_radio_never_counts_as_a_listen():
    from musi.player.scrobbler import Scrobbler
    listened, started = [], []
    s = Scrobbler(on_start=started.append, on_listen=lambda m, t: listened.append(m))
    for i in range(400):
        s.update(Status("http://glz/glglz_mp3"), now=i, wall=i)
    s.update(Status("/m/next.flac"), now=401, wall=401)
    assert listened == [] and [m["path"] for m in started] == ["/m/next.flac"]


def test_launcher_subtitle():
    from musi.player.screens.radio import subtitle
    app = App("/m/local.flac")
    assert subtitle(app) == "Search stations"
    radio.toggle_saved({"provider": "tunein", "id": "s1", "name": "GLGLZ"})
    assert subtitle(app) == "1 saved station"
    radio.note_playing("http://glz/x", {"provider": "tunein", "id": "s1", "name": "GLGLZ"})
    app.status.path = "http://glz/x"
    assert subtitle(app) == "On air: GLGLZ"


def test_radio_screens_draw(monkeypatch):
    from musi.player.screens.radio import RadioScreen, RadioSearchScreen
    monkeypatch.setattr(radio, "tunein_local", lambda: [])
    radio.toggle_saved({"provider": "tunein", "id": "s1", "name": "GLGLZ", "image": ""})
    app = App()
    for scr in (RadioScreen(app), RadioSearchScreen(app, "glglz")):
        app.stack.append(scr)
        scr.draw(pygame.Surface((320, 480)), app.status)


# ── right-to-left text ────────────────────────────────────────────────────────

def test_hebrew_is_reordered_for_display_and_latin_is_untouched():
    from musi.player import theme
    shalom = "שלום"
    assert theme.visual(shalom) == shalom[::-1]
    assert theme.visual("GLGLZ 100FM") == "GLGLZ 100FM"
