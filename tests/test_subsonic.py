"""Music-server streaming — Subsonic client, catalog sync, stream redirect, UI.

No network: a FakeServer stands in for Navidrome by answering the Subsonic
calls the client makes, so the tests pin the contract (auth scheme, paging,
fallbacks) rather than one server's quirks.
"""
import hashlib
import io
import json
import os
import threading
import urllib.parse

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest
from PIL import Image

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library import remote, subsonic
from musi.library.db import open_db, run_migrations
from musi.library.subsonic import Client, SubsonicError
from musi.library.subsonic_sync import remove_all, sync


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_SUBSONIC_PATH", str(tmp_path / "subsonic.json"))
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 40, 90)).save(buf, "PNG")
    return buf.getvalue()


class FakeServer:
    """Answers Subsonic REST calls from in-memory albums and songs."""

    def __init__(self, password="pw", search3=True):
        self.password = password
        self.search3 = search3
        self.albums = [
            {"id": "al1", "name": "Cloud Album", "artist": "Remote Band",
             "year": 2020, "coverArt": "al-al1"},
            {"id": "al2", "name": "Shared Album", "artist": "Local Band",
             "coverArt": "al-al2"},
        ]
        self.songs = [
            {"id": "s1", "title": "Up", "album": "Cloud Album", "albumId": "al1",
             "artist": "Remote Band", "track": 1, "duration": 200},
            {"id": "s2", "title": "Down", "album": "Cloud Album", "albumId": "al1",
             "artist": "Remote Band", "track": 2, "duration": 180},
            # same as a local track → skipped (local wins)
            {"id": "s3", "title": "Mine", "album": "Shared Album", "albumId": "al2",
             "artist": "Local Band", "track": 1, "duration": 100},
            # only on the server → joins the local album
            {"id": "s4", "title": "Theirs", "album": "Shared Album", "albumId": "al2",
             "artist": "Local Band", "track": 2, "duration": 110},
        ]
        self.calls = []

    def __call__(self, url: str) -> bytes:
        parts = urllib.parse.urlparse(url)
        method = parts.path.rsplit("/", 1)[-1]
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((method, q))
        expect = hashlib.md5((self.password + q["s"]).encode()).hexdigest()
        if q.get("t") != expect:
            return _resp({"status": "failed",
                          "error": {"code": 40, "message": "Wrong username or password"}})
        if method == "getCoverArt":
            return _png()
        if method == "ping":
            return _resp({"status": "ok"})
        if method == "getAlbumList2":
            off, size = int(q["offset"]), int(q["size"])
            return _resp({"status": "ok",
                          "albumList2": {"album": self.albums[off:off + size]}})
        if method == "search3":
            if not self.search3:
                return _resp({"status": "ok", "searchResult3": {}})
            off, size = int(q["songOffset"]), int(q["songCount"])
            return _resp({"status": "ok",
                          "searchResult3": {"song": self.songs[off:off + size]}})
        if method == "getAlbum":
            songs = [s for s in self.songs if s["albumId"] == q["id"]]
            return _resp({"status": "ok", "album": {"song": songs}})
        if method == "scrobble":
            return _resp({"status": "ok"})
        return _resp({"status": "failed", "error": {"code": 0, "message": "?"}})


def _resp(body: dict) -> bytes:
    return json.dumps({"subsonic-response": body}).encode()


def _client(server: FakeServer, password="pw") -> Client:
    return Client("http://nas:4533/", "me", password, opener=server)


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "library.db")
    run_migrations(conn)
    artist = conn.execute("INSERT INTO artists (name) VALUES ('Local Band')").lastrowid
    album = conn.execute(
        "INSERT INTO albums (artist_id, title, art_path, palette) VALUES (?,?,?,?)",
        (artist, "Shared Album", "/art/local.jpg", "[]")).lastrowid
    conn.execute(
        "INSERT INTO tracks (album_id, artist_id, path, title, track_number) "
        "VALUES (?,?,?,?,1)", (album, artist, str(tmp_path / "mine.mp3"), "Mine"))
    conn.commit()
    yield conn
    conn.close()


def _remote_titles(conn):
    return sorted(r[0] for r in conn.execute(
        "SELECT title FROM tracks WHERE path LIKE 'http%'"))


# ── stream URLs ───────────────────────────────────────────────────────────────

def test_stream_urls_round_trip_and_hold_no_secret():
    url = remote.stream_url("abc123")
    assert remote.is_remote(url)
    assert remote.song_id(url) == "abc123"
    assert "t=" not in url and "p=" not in url
    assert not remote.is_remote("/home/pi/music/a.flac")
    assert not remote.is_remote(None)
    assert remote.song_id("http://elsewhere/x") is None


# ── client ────────────────────────────────────────────────────────────────────

def test_requests_use_a_salted_token_never_the_password():
    server = FakeServer()
    _client(server).ping()
    method, q = server.calls[0]
    assert method == "ping"
    assert "p" not in q and "pw" not in q.values()
    assert q["t"] == hashlib.md5(("pw" + q["s"]).encode()).hexdigest()
    assert q["u"] == "me" and q["c"] == "musi" and q["f"] == "json"


def test_every_request_gets_a_fresh_salt():
    c = _client(FakeServer())
    a = urllib.parse.parse_qs(urllib.parse.urlparse(c.url_for("ping")).query)
    b = urllib.parse.parse_qs(urllib.parse.urlparse(c.url_for("ping")).query)
    assert a["s"] != b["s"]


def test_wrong_password_raises_the_servers_message():
    with pytest.raises(SubsonicError, match="Wrong username or password"):
        _client(FakeServer(), password="nope").ping()


def test_a_non_subsonic_reply_is_reported_as_such():
    c = Client("http://router", "me", "pw", opener=lambda url: b"<html>hi</html>")
    with pytest.raises(SubsonicError, match="not a Subsonic server"):
        c.ping()


def test_unreachable_server_is_a_subsonic_error():
    def boom(url):
        raise OSError("no route to host")
    with pytest.raises(SubsonicError, match="can't reach server"):
        Client("http://nas", "me", "pw", opener=boom).ping()


def test_raw_stream_by_default_so_seeking_works():
    q = urllib.parse.parse_qs(urllib.parse.urlparse(
        _client(FakeServer()).stream_url("s1")).query)
    assert q["format"] == ["raw"] and q["id"] == ["s1"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(
        _client(FakeServer()).stream_url("s1", max_bitrate=192)).query)
    assert q["maxBitRate"] == ["192"] and "format" not in q


@pytest.mark.parametrize("typed,want", [
    ("192.168.1.20:4533", "http://192.168.1.20:4533"),
    ("https://music.example.com/", "https://music.example.com"),
    ("  nas:4533/  ", "http://nas:4533"),
])
def test_typed_urls_are_forgiven(typed, want):
    assert subsonic.normalize_url(typed) == want


def test_settings_round_trip_and_merge():
    assert subsonic.load_settings() is None
    subsonic.save_settings({"url": "http://nas", "username": "me", "password": "pw"})
    subsonic.update_settings(last_sync=5, password=None)
    s = subsonic.load_settings()
    assert s["last_sync"] == 5 and "password" not in s
    subsonic.clear_settings()
    assert subsonic.load_settings() is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_settings_file_is_owner_only(tmp_path):
    subsonic.save_settings({"url": "http://nas", "username": "me", "password": "pw"})
    mode = os.stat(tmp_path / "subsonic.json").st_mode & 0o777
    assert mode == 0o600


# ── sync ──────────────────────────────────────────────────────────────────────

def test_sync_mirrors_the_server_and_local_wins(db, tmp_path):
    stats = sync(_client(FakeServer()), db, tmp_path / "art")
    assert stats["added"] == 3 and stats["skipped_local"] == 1
    assert _remote_titles(db) == ["Down", "Theirs", "Up"]
    # "Theirs" merged into the existing local album rather than a duplicate
    albums = db.execute("SELECT COUNT(*) FROM albums WHERE title = 'Shared Album'").fetchone()[0]
    assert albums == 1
    row = db.execute("SELECT path, duration FROM tracks WHERE title = 'Up'").fetchone()
    assert row["path"] == remote.stream_url("s1") and row["duration"] == 200


def test_sync_fetches_server_covers_but_keeps_local_art(db, tmp_path):
    sync(_client(FakeServer()), db, tmp_path / "art")
    cloud = db.execute("SELECT art_path, palette FROM albums WHERE title = 'Cloud Album'").fetchone()
    assert cloud["art_path"] and os.path.exists(cloud["art_path"])
    assert json.loads(cloud["palette"])
    shared = db.execute("SELECT art_path FROM albums WHERE title = 'Shared Album'").fetchone()
    assert shared["art_path"] == "/art/local.jpg"


def test_resync_updates_in_place_and_drops_what_the_server_lost(db, tmp_path):
    server = FakeServer()
    sync(_client(server), db, tmp_path / "art")
    track_id = db.execute("SELECT id FROM tracks WHERE title = 'Down'").fetchone()[0]
    db.execute("INSERT INTO play_history (track_id) VALUES (?)", (track_id,))
    db.commit()

    server.songs = [s for s in server.songs if s["id"] != "s2"]
    server.songs[0]["title"] = "Up (Remaster)"
    stats = sync(_client(server), db, tmp_path / "art")
    assert (stats["added"], stats["updated"], stats["removed"]) == (0, 2, 1)
    assert _remote_titles(db) == ["Theirs", "Up (Remaster)"]
    # the local track is never the sync's business
    assert db.execute("SELECT COUNT(*) FROM tracks WHERE title = 'Mine'").fetchone()[0] == 1


def test_sync_falls_back_to_album_walk_without_search3(db, tmp_path):
    stats = sync(_client(FakeServer(search3=False)), db, tmp_path / "art")
    assert stats["added"] == 3


def test_sync_writes_bookkeeping_to_settings(db, tmp_path):
    subsonic.save_settings({"url": "http://nas", "username": "me", "password": "pw"})
    sync(_client(FakeServer()), db, tmp_path / "art")
    s = subsonic.load_settings()
    assert s["track_count"] == 3 and s["last_sync"] > 0


def test_sign_out_removes_only_server_tracks(db, tmp_path):
    sync(_client(FakeServer()), db, tmp_path / "art")
    assert remove_all(db) == 3
    assert _remote_titles(db) == []
    assert db.execute("SELECT COUNT(*) FROM albums WHERE title = 'Cloud Album'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1


def test_the_scanner_never_prunes_server_tracks(db, tmp_path):
    from musi.library.scanner import scan
    sync(_client(FakeServer()), db, tmp_path / "art")
    music = tmp_path / "music"
    music.mkdir()
    scan(music, tmp_path / "art", db)
    assert _remote_titles(db) == ["Down", "Theirs", "Up"]


def test_artwork_fetcher_ignores_server_albums(db, tmp_path):
    from musi.library.art_fetch import albums_missing_art
    sync(_client(FakeServer()), db, tmp_path / "art")
    titles = {a["album"] for a in albums_missing_art(db)}
    assert "Cloud Album" not in titles


# ── API: stream redirect + setup ──────────────────────────────────────────────

TOKEN = "ABCD2345"


@pytest.fixture
def api(tmp_path):
    from musi.api.server import create_app
    (tmp_path / "music").mkdir()
    (tmp_path / "art").mkdir(exist_ok=True)
    app = create_app(tmp_path / "music", tmp_path / "library.db", tmp_path / "art",
                     token_provider=lambda: TOKEN, cors_origins=set())
    app.testing = True
    return app.test_client()


def test_stream_redirect_is_loopback_only(api):
    subsonic.save_settings({"url": "http://nas:4533", "username": "me", "password": "pw"})
    r = api.get("/local/subsonic/stream/s1", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 302
    loc = urllib.parse.urlparse(r.headers["Location"])
    assert loc.netloc == "nas:4533" and loc.path == "/rest/stream"
    q = urllib.parse.parse_qs(loc.query)
    assert q["id"] == ["s1"] and "t" in q
    r = api.get("/local/subsonic/stream/s1", environ_base={"REMOTE_ADDR": "192.168.1.9"},
                headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 403


def test_stream_redirect_without_a_server_is_404(api):
    r = api.get("/local/subsonic/stream/s1", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 404


def test_api_setup_needs_the_token(api):
    assert api.get("/api/v1/subsonic").status_code == 401


def test_api_state_never_includes_the_password(api):
    subsonic.save_settings({"url": "http://nas", "username": "me", "password": "secret"})
    r = api.get("/api/v1/subsonic", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json["configured"] and r.json["username"] == "me"
    assert "secret" not in r.get_data(as_text=True)


def test_api_put_refuses_a_bad_login(api, monkeypatch):
    def ping(self):
        raise SubsonicError("Wrong username or password", 40)
    monkeypatch.setattr(Client, "ping", ping)
    r = api.put("/api/v1/subsonic", headers={"Authorization": f"Bearer {TOKEN}"},
                json={"url": "nas:4533", "username": "me", "password": "x"})
    assert r.status_code == 400 and "Wrong" in r.json["error"]
    assert subsonic.load_settings() is None


# ── player side ───────────────────────────────────────────────────────────────

def test_mpd_client_passes_stream_urls_through_untouched(tmp_path):
    from musi.player.mpd_client import MusiMPDClient
    c = MusiMPDClient(tmp_path)
    url = remote.stream_url("s1")
    assert c._to_relative(url) == url
    assert c._to_absolute(url) == url
    assert c._to_absolute("a/b.flac") == str(tmp_path / "a/b.flac")
    assert c._to_relative(str(tmp_path / "a" / "b.flac")) == "a/b.flac"


def test_poll_names_a_stream_from_the_library(tmp_path):
    from musi.player.mpd_client import MusiMPDClient
    url = remote.stream_url("s1")

    class Sock:
        def status(self):
            return {"state": "play", "volume": "50", "elapsed": "3"}

        def currentsong(self):
            return {"file": url}

    c = MusiMPDClient(tmp_path)
    c._client, c._connected = Sock(), True
    c._ensure = lambda: True
    c.remote_meta = lambda u: {"title": "Up", "artist": "Remote Band",
                               "album": "Cloud Album", "duration": 200}
    st = c.poll()
    assert (st.path, st.title, st.artist, st.duration) == (url, "Up", "Remote Band", 200.0)


def test_cloud_tag_is_baked_into_the_now_playing_title():
    from musi.player import icons
    from musi.player.screens.now_playing import NowPlayingScreen

    class S:
        title, artist, album = "Up", "Remote Band", "Cloud Album"
        path = remote.stream_url("s1")
        state, duration, progress, elapsed = "play", 200.0, 0.0, 0.0

    scr = NowPlayingScreen.__new__(NowPlayingScreen)
    scr._prev_title, scr._prev_meta, scr._prev_elapsed = ("", False), "", -1
    scr._update_text_cache(S())
    tagged = scr._title_surf.get_width()
    S.path = "/m/up.flac"
    scr._update_text_cache(S())
    assert tagged == scr._title_surf.get_width() + icons.CLOUD_W


class _App:
    db = None
    art_dir = None
    stack: list = []

    def toggle_play(self):
        pass


def test_server_screen_only_connects_a_complete_login():
    from musi.player.screens.music_server import MusicServerScreen
    scr = MusicServerScreen(_App())
    assert scr._action() == ("Connect", False)
    scr.draft.update(url="http://nas", username="me", password="pw")
    assert scr._action() == ("Connect", True)


def test_server_screen_offers_sync_once_saved():
    from musi.player.screens.music_server import MusicServerScreen
    subsonic.save_settings({"url": "http://nas", "username": "me", "password": "pw",
                            "track_count": 42, "last_sync": 1})
    scr = MusicServerScreen(_App())
    assert scr._action() == ("Sync now", True)
    assert scr.summary()[0].startswith("42 songs")
    scr.draft["url"] = "http://other"
    assert scr._action() == ("Connect", True)


# ── background sync ───────────────────────────────────────────────────────────

from musi.library import subsonic_sync as ss  # noqa: E402

H = 3600


@pytest.mark.parametrize("settings,now,uptime,due", [
    (None,                                   10 * H, 10 * H, False),  # no server
    ({"url": "x", "last_sync": 0},           10 * H, 60,     False),  # just booted
    ({"url": "x", "last_sync": 0},           10 * H, 10 * H, True),
    ({"url": "x", "last_sync": 9 * H},       10 * H, 10 * H, False),  # synced 1 h ago
    ({"url": "x", "last_sync": 0, "last_auto_try": 10 * H - 60}, 10 * H, 10 * H, False),
    ({"url": "x", "last_sync": 0, "last_auto_try": 9 * H},       10 * H, 10 * H, True),
    ({"url": "x", "last_sync": 0, "auto_sync": False},           10 * H, 10 * H, False),
])
def test_auto_sync_schedule(settings, now, uptime, due):
    assert ss.auto_due(settings, now, uptime) is due


def test_maybe_auto_sync_records_the_attempt(tmp_path, monkeypatch):
    subsonic.save_settings({"url": "http://nas", "username": "me", "password": "pw"})
    started = []
    monkeypatch.setattr(ss.job, "start", lambda db, art: started.append(db) or True)
    assert ss.maybe_auto_sync(tmp_path / "db", tmp_path / "art", uptime=10 * H, now=10 * H)
    assert started and subsonic.load_settings()["last_auto_try"] == 10 * H
    # a minute later it is not due again, even though no sync has succeeded
    assert not ss.maybe_auto_sync(tmp_path / "db", tmp_path / "art",
                                  uptime=10 * H + 60, now=10 * H + 60)
