"""MusiMPDClient unit tests (no real MPD — fake socket client)."""
from musi.player.mpd_client import MusiMPDClient


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
