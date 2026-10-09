"""Player settings from the web page — the API side and the player picking it up."""
import json
import os
import time

import pytest

from musi.api import server
from musi.player import prefs

TOKEN = "ABCD2345"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MUSI_LISTENBRAINZ_PATH", str(tmp_path / "lb.json"))
    monkeypatch.setenv("MUSI_SUBSONIC_PATH", str(tmp_path / "subsonic.json"))
    prefs.reload()
    yield
    prefs.reload()


@pytest.fixture
def api(tmp_path, monkeypatch):
    (tmp_path / "music").mkdir()
    (tmp_path / "art").mkdir()
    pushed = []
    monkeypatch.setattr(server, "_mpd_apply", lambda **kw: pushed.append(kw))
    app = server.create_app(tmp_path / "music", tmp_path / "library.db", tmp_path / "art",
                            token_provider=lambda: TOKEN, cors_origins=set())
    app.testing = True
    c = app.test_client()
    c.pushed = pushed
    return c


def test_settings_need_the_token(api):
    assert api.get("/api/v1/settings").status_code == 401
    assert api.patch("/api/v1/settings", json={"crossfade": True}).status_code == 401


def test_get_lists_values_and_choices(api):
    d = api.get("/api/v1/settings", headers=AUTH).json
    assert d["values"]["crossfade"] is False and d["values"]["animations"] is True
    assert d["choices"]["wallpaper"] == ["none", "warm", "cool"]


def test_patch_saves_and_pushes_playback_settings_to_mpd(api, tmp_path):
    r = api.patch("/api/v1/settings", headers=AUTH,
                  json={"crossfade": True, "listenbrainz_skip_server": True})
    assert r.status_code == 200 and r.json["values"]["crossfade"] is True
    on_disk = json.loads((tmp_path / "prefs.json").read_text())
    assert on_disk["crossfade"] is True and on_disk["listenbrainz_skip_server"] is True
    assert api.pushed == [{"crossfade": True, "replaygain": None}]


def test_display_settings_do_not_touch_mpd(api):
    api.patch("/api/v1/settings", headers=AUTH, json={"wallpaper": "warm"})
    assert api.pushed == []


@pytest.mark.parametrize("body", [{"crossfade": "yes"}, {"wallpaper": "pink"},
                                  {"volume": 50}, {}, ["crossfade"]])
def test_bad_settings_are_refused_whole(api, body, tmp_path):
    r = api.patch("/api/v1/settings", headers=AUTH, json=body)
    assert r.status_code == 400
    assert not (tmp_path / "prefs.json").exists()


def test_the_page_has_the_settings_tab(api):
    html = api.get("/").get_data(as_text=True)
    assert 'id="tab-set"' in html and 'data-pref="listenbrainz_skip_server"' in html


# ── the player picks up a change made by the API process ──────────────────────

def test_a_change_from_another_process_is_picked_up(tmp_path):
    assert prefs.get("animations") is True          # player has the file cached
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"animations": False}))
    later = time.time() + 5                         # make sure the mtime moves
    os.utime(path, (later, later))
    assert prefs.refresh_if_changed() is True
    assert prefs.get("animations") is False
    assert prefs.refresh_if_changed() is False      # nothing new since


def test_our_own_write_is_not_a_change():
    prefs.set("crossfade", True)
    assert prefs.refresh_if_changed() is False


# ── the new scrobbling option ─────────────────────────────────────────────────

def test_server_songs_can_be_left_to_navidrome(monkeypatch):
    from musi.library import listenbrainz, remote, subsonic
    from musi.player import scrobbler
    sent, scrobbled = [], []
    monkeypatch.setattr(listenbrainz, "record_listen", lambda m, t: sent.append(m["path"]))
    monkeypatch.setattr(subsonic, "scrobble_async", lambda p, submission=True: scrobbled.append(p))
    server_song = {"path": remote.stream_url("s1")}
    local_song = {"path": "/m/a.flac"}

    prefs.set("listenbrainz_skip_server", True)
    scrobbler._default_listen(server_song, 0)
    scrobbler._default_listen(local_song, 0)
    assert sent == ["/m/a.flac"]                    # ListenBrainz: local only
    assert scrobbled == [server_song["path"]]       # Navidrome still told

    prefs.set("listenbrainz_skip_server", False)
    scrobbler._default_listen(server_song, 0)
    assert sent[-1] == server_song["path"]
