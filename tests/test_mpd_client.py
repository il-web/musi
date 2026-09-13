"""MusiMPDClient unit tests (no real MPD — fake socket client)."""
import threading
import time

from musi.player.mpd_client import (FAVORITES, MusiMPDClient, PlaylistInfo,
                                    _safe_playlist_name)


class FakeSocketClient:
    def __init__(self):
        self.calls = []

    def ping(self):
        pass

    def random(self, v):
        self.calls.append(("random", v))


def _client_with_fake():
    c = MusiMPDClient.__new__(MusiMPDClient)   # skip __init__/connect
    c._connected = True
    c._lock = threading.RLock()               # __init__ normally provides this
    c._client = FakeSocketClient()
    return c


def test_set_shuffle_on_off():
    c = _client_with_fake()
    c.set_shuffle(True)
    c.set_shuffle(False)
    assert c._client.calls == [("random", 1), ("random", 0)]


class FakeMPD:
    """Mimics python-mpd2's socket lifetime, which is what the bug turns on.

    The real client refuses connect() while a socket object is still attached
    (base.py:782 raises ConnectionError("Already connected")), and only
    disconnect() clears it. A command that fails mid-session leaves the socket
    attached but dead.
    """

    def __init__(self):
        self._sock = None
        self.timeout = None
        self.fail = False        # make commands raise, socket still attached
        self.refuse = False      # make connect() fail, as a dead MPD would

    def connect(self, host, port):
        if self._sock is not None:
            raise ConnectionError("Already connected")
        if self.refuse:
            raise ConnectionError("Connection refused")
        self._sock = object()

    def disconnect(self):
        self._sock = None

    def close(self):
        pass

    def _cmd(self):
        if self._sock is None:
            raise ConnectionError("Not connected")
        if self.fail:
            raise ConnectionError("connection timed out")

    def ping(self):
        self._cmd()

    def status(self):
        self._cmd()
        return {"state": "play", "volume": "50", "playlistlength": "1"}

    def currentsong(self):
        self._cmd()
        return {"file": "a.flac"}


def _live_client(tmp_path):
    c = MusiMPDClient(music_root=tmp_path)
    c._client = FakeMPD()
    return c


def test_it_recovers_after_a_command_fails_mid_session(tmp_path):
    """MPD stalling once — a status() timeout while it scans at boot — must not
    wedge the client forever. Before the fix the dead socket stayed attached,
    so every later connect() raised "Already connected" and the UI showed
    "Not connected" until the process was restarted."""
    c = _live_client(tmp_path)
    assert c.connect() is True
    assert c.poll().connected is True

    c._client.fail = True                 # MPD stops answering
    assert c.poll().connected is False

    c._client.fail = False                # MPD recovers
    c._next_retry = 0.0                   # skip the backoff window
    assert c.poll().connected is True


def test_a_failed_ping_does_not_wedge_the_client(tmp_path):
    """The other entry point into the same trap: _ensure() pings, the ping
    fails, and the socket is left attached."""
    c = _live_client(tmp_path)
    assert c.connect() is True

    c._client.fail = True
    c._client.refuse = True           # MPD is gone, not merely slow
    assert c._ensure() is False

    c._client.fail = False            # and comes back
    c._client.refuse = False
    c._next_retry = 0.0
    assert c._ensure() is True


def test_a_refused_connect_still_retries_cleanly(tmp_path):
    """The startup race: MPD not listening yet must stay recoverable."""
    c = _live_client(tmp_path)
    c._client.refuse = True
    assert c.connect() is False

    c._client.refuse = False
    c._next_retry = 0.0
    assert c.connect() is True


class ReentrancyDetector(FakeMPD):
    """Fails loudly if two threads are inside the client at the same time.

    python-mpd2 is not thread-safe: a command writes to the socket then reads
    the reply, so two overlapping callers desync the protocol. At startup the
    loading screen's thread calls connect() every 0.4 s while the main loop
    polls every 1.0 s, so this overlap is the normal case, not a rare one.
    """

    def __init__(self):
        super().__init__()
        self.inside = 0
        self.overlaps = 0

    def _enter(self):
        self.inside += 1
        if self.inside > 1:
            self.overlaps += 1
        time.sleep(0.005)          # widen the window so the race is reliable

    def _exit(self):
        self.inside -= 1

    def connect(self, host, port):
        self._enter()
        try:
            super().connect(host, port)
        finally:
            self._exit()

    def status(self):
        self._enter()
        try:
            return super().status()
        finally:
            self._exit()

    def currentsong(self):
        self._enter()
        try:
            return super().currentsong()
        finally:
            self._exit()

    def ping(self):
        self._enter()
        try:
            super().ping()
        finally:
            self._exit()


def test_concurrent_callers_are_serialised(tmp_path):
    """Reproduces the startup overlap: a reconnect loop racing the status poll.

    Without a lock the two interleave inside the client, which is what
    desyncs a real MPD socket and leaves the UI stuck on "Not connected"."""
    c = _live_client(tmp_path)
    c._client = ReentrancyDetector()
    c.connect()

    stop = threading.Event()

    def reconnector():
        while not stop.is_set():
            c._next_retry = 0.0
            c.connect()

    def poller():
        while not stop.is_set():
            c.poll()

    threads = [threading.Thread(target=reconnector), threading.Thread(target=poller)]
    for t in threads:
        t.start()
    time.sleep(0.4)
    stop.set()
    for t in threads:
        t.join()

    assert c._client.overlaps == 0, (
        f"{c._client.overlaps} overlapping entries — two threads were inside "
        "the MPD client at once"
    )


# ── stored playlists + favourites ───────────────────────────────────────────

class FakePlaylistMPD(FakeMPD):
    """In-memory stand-in for MPD's stored-playlist + queue commands."""

    def __init__(self):
        super().__init__()
        self.lists: dict[str, list[str]] = {}
        self.queue_uris: list[str] = []
        self.calls: list = []

    def listplaylists(self):
        return [{"playlist": name} for name in self.lists]

    def listplaylist(self, name):
        if name not in self.lists:
            raise ValueError("No such playlist")
        return list(self.lists[name])

    def listplaylistinfo(self, name):
        if name not in self.lists:
            raise ValueError("No such playlist")
        return [{"file": uri, "title": uri.rsplit("/", 1)[-1], "duration": "60"}
                for uri in self.lists[name]]

    def playlistadd(self, name, uri):
        self.lists.setdefault(name, []).append(uri)

    def playlistdelete(self, name, pos):
        del self.lists[name][pos]

    def playlistmove(self, name, frm, to):
        item = self.lists[name].pop(frm)
        self.lists[name].insert(to, item)

    def rename(self, old, new):
        self.lists[new] = self.lists.pop(old)

    def rm(self, name):
        if name not in self.lists:
            raise ValueError("No such playlist")
        del self.lists[name]

    def save(self, name):
        self.lists[name] = list(self.queue_uris)

    def clear(self):
        self.calls.append(("clear",))

    def load(self, name):
        self.calls.append(("load", name))

    def random(self, v):
        self.calls.append(("random", v))

    def play(self, i):
        self.calls.append(("play", i))


def _playlist_client(tmp_path):
    c = MusiMPDClient(music_root=tmp_path)
    c._client = FakePlaylistMPD()
    c.connect()
    return c


def test_safe_playlist_name_strips_path_chars_and_trims():
    assert _safe_playlist_name("  road/trip  ") == "roadtrip"
    assert _safe_playlist_name("...hidden") == "hidden"
    assert _safe_playlist_name("x" * 80) == "x" * 40
    assert _safe_playlist_name("a\\b\tc") == "abc"


def test_playlist_add_stores_paths_relative_to_the_music_root(tmp_path):
    c = _playlist_client(tmp_path)
    c.playlist_add("Mix", [tmp_path / "band" / "song.flac"])
    assert c._client.lists["Mix"] == ["band/song.flac"]


def test_playlist_add_sanitises_the_name(tmp_path):
    c = _playlist_client(tmp_path)
    c.playlist_add("a/b", [tmp_path / "s.mp3"])
    assert "ab" in c._client.lists and "a/b" not in c._client.lists


def test_toggle_favorite_adds_then_removes(tmp_path):
    c = _playlist_client(tmp_path)
    p = str(tmp_path / "x.mp3")

    assert c.is_favorite(p) is False
    assert c.toggle_favorite(p) is True
    assert c._client.lists[FAVORITES] == ["x.mp3"]
    assert c.is_favorite(p) is True
    assert c.toggle_favorite(p) is False
    assert c._client.lists[FAVORITES] == []


def test_is_favorite_false_when_the_list_does_not_exist(tmp_path):
    c = _playlist_client(tmp_path)
    assert c.is_favorite(str(tmp_path / "x.mp3")) is False


def test_list_playlists_puts_favorites_first_then_case_insensitive(tmp_path):
    c = _playlist_client(tmp_path)
    c._client.lists = {"Zed": ["a"], FAVORITES: ["a", "b"], "abba": []}
    got = c.list_playlists()
    assert [p.name for p in got] == [FAVORITES, "abba", "Zed"]
    assert got[0] == PlaylistInfo(FAVORITES, 2)


def test_save_queue_as_replaces_any_namesake(tmp_path):
    c = _playlist_client(tmp_path)
    c._client.lists["Trip"] = ["old1", "old2"]
    c._client.queue_uris = ["new1", "new2", "new3"]
    c.save_queue_as("Trip")
    assert c._client.lists["Trip"] == ["new1", "new2", "new3"]


def test_playlist_move_reorders_in_place(tmp_path):
    c = _playlist_client(tmp_path)
    c._client.lists["Mix"] = ["a", "b", "c", "d"]
    c.playlist_move("Mix", 0, 2)
    assert c._client.lists["Mix"] == ["b", "c", "a", "d"]


def test_playlist_tracks_returns_absolute_paths(tmp_path):
    c = _playlist_client(tmp_path)
    c._client.lists["Mix"] = ["band/song.flac"]
    tracks = c.playlist_tracks("Mix")
    assert tracks[0]["path"] == str(tmp_path / "band" / "song.flac")
    assert tracks[0]["duration"] == 60.0


def test_play_playlist_clears_loads_and_plays(tmp_path):
    c = _playlist_client(tmp_path)
    c.play_playlist("Mix", start_index=2, shuffle=True)
    assert c._client.calls == [("clear",), ("load", "Mix"), ("random", 1), ("play", 2)]
