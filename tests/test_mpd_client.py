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
