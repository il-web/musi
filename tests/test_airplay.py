"""AirPlay — metadata pipe parsing, the status overlay, controls, handover."""
import base64
import os
import threading

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library import remote
from musi.player import airplay
from musi.player.mpd_client import PlayerStatus


def item(kind: str, code: str, data: bytes | None = None) -> str:
    """One metadata item exactly as shairport-sync writes it."""
    hexs = lambda s: s.encode().hex()
    if data is None:
        return f"<item><type>{hexs(kind)}</type><code>{hexs(code)}</code><length>0</length></item>\n"
    b64 = base64.b64encode(data).decode()
    return (f"<item><type>{hexs(kind)}</type><code>{hexs(code)}</code>"
            f"<length>{len(data)}</length>\n<data encoding=\"base64\">\n{b64}</data></item>\n")


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(airplay, "FLAG", str(tmp_path / "musi-airplay"))
    with airplay._lock:
        airplay._meta.update(title="", artist="", album="", art=b"", art_rev=0, track=0,
                             paused=False, start=None, now=None, end=None, at=0.0, source="")
    airplay._cover_cache = None
    yield


def _png() -> bytes:
    s = pygame.Surface((8, 8))
    s.fill((200, 40, 90))
    import io
    buf = io.BytesIO()
    pygame.image.save(s, buf, "x.png")
    return buf.getvalue()


def test_metadata_items_fill_in_the_song():
    text = (item("core", "minm", b"Houdini") + item("core", "asar", b"Dua Lipa")
            + item("core", "asal", "Radical Optimism".encode())
            + item("ssnc", "snam", "Ilay’s iPhone".encode()))
    assert airplay.feed(text) == "\n"          # all items consumed
    m = airplay.snapshot()
    assert (m["title"], m["artist"], m["album"]) == ("Houdini", "Dua Lipa", "Radical Optimism")
    assert m["source"] == "Ilay’s iPhone"


def test_an_item_split_across_reads_is_kept_for_the_next_one():
    whole = item("core", "minm", b"Houdini")
    tail = airplay.feed(whole[:30])
    assert airplay.snapshot()["title"] == ""
    airplay.feed(tail + whole[30:])
    assert airplay.snapshot()["title"] == "Houdini"


def test_a_new_title_is_a_new_track():
    airplay.feed(item("core", "minm", b"One"))
    first = airplay.snapshot()["track"]
    airplay.feed(item("core", "minm", b"One"))          # repeated: same song
    assert airplay.snapshot()["track"] == first
    airplay.feed(item("core", "minm", b"Two"))
    assert airplay.snapshot()["track"] == first + 1


def test_progress_is_extrapolated_while_playing_and_frozen_when_paused(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(airplay.time, "monotonic", lambda: clock[0])
    start = 1_000_000
    airplay.feed(item("ssnc", "prgr", f"{start}/{start + 44100 * 10}/{start + 44100 * 185}".encode()))
    clock[0] += 5
    elapsed, duration = airplay.position()
    assert duration == pytest.approx(185) and elapsed == pytest.approx(15)
    airplay.feed(item("ssnc", "pfls"))                  # paused on the phone
    clock[0] += 30
    assert airplay.position()[0] == pytest.approx(15)


def test_overlay_shows_the_phones_song_on_the_player():
    airplay.feed(item("core", "minm", b"Houdini") + item("core", "asar", b"Dua Lipa"))
    st = airplay.overlay(PlayerStatus.disconnected())
    assert st.connected and st.state == "play"
    assert (st.title, st.artist) == ("Houdini", "Dua Lipa")
    assert remote.kind(st.path) == "airplay"


def test_the_cover_becomes_an_opaque_surface():
    airplay.feed(item("ssnc", "PICT", _png()))
    surf = airplay.cover((32, 32))
    assert surf.get_size() == (32, 32) and not (surf.get_flags() & pygame.SRCALPHA)
    assert airplay.cover((32, 32)) is surf               # cached per cover


def test_controls_go_to_the_phone_over_mpris(monkeypatch):
    calls = []
    monkeypatch.setattr(airplay.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})())

    class Inline:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(airplay.threading, "Thread", Inline)
    airplay.command("Next")
    assert calls == [["busctl", "--user", "call", "org.mpris.MediaPlayer2.ShairportSync",
                      "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Next"]]


def test_taking_the_speaker_back_ends_the_session(tmp_path, monkeypatch):
    open(airplay.FLAG, "w").write("1")
    calls = []
    monkeypatch.setattr(airplay.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    airplay.end_session()
    assert not airplay.active()
    assert calls == [["systemctl", "--user", "restart", "musi-airplay"]]


def test_playing_musi_music_first_releases_airplay(tmp_path):
    from musi.player.mpd_client import MusiMPDClient

    class Sock:
        def ping(self): pass
        def clear(self): pass
        def add(self, p): pass
        def play(self, i=0): pass

    released = []
    c = MusiMPDClient(tmp_path)
    c._client, c._connected = Sock(), True
    c._ensure = lambda: True
    c.before_play = lambda: released.append(True)
    c.play_paths(["/m/a.flac"])
    assert released == [True]


def test_play_pause_controls_the_phone_while_it_plays(tmp_path, monkeypatch):
    from musi.player.app import App
    sent = []
    monkeypatch.setattr(airplay, "command", sent.append)
    open(airplay.FLAG, "w").write("1")

    class MPD:
        before_play = None
        def play_pause(self):
            raise AssertionError("MPD must not be touched during AirPlay")

    app = App(mpd=MPD(), db=None, art_dir=tmp_path, lyrics_dir=tmp_path)
    app._status = airplay.overlay(PlayerStatus.disconnected())
    app.toggle_play()
    assert sent == ["PlayPause"] and app.status.state == "pause"


def test_airplay_is_never_scrobbled():
    from musi.player.scrobbler import Scrobbler
    listened = []
    s = Scrobbler(on_start=lambda m: None, on_listen=lambda m, t: listened.append(m))
    st = airplay.overlay(PlayerStatus.disconnected())
    for i in range(400):
        st.elapsed = float(i)
        s.update(st, now=i, wall=i)
    s.update(PlayerStatus.disconnected(), now=401, wall=401)
    assert listened == []
