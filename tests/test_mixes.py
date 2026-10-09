"""Smart mixes — history, ListenBrainz matching, song radio."""
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pytest

from musi.library import mixes, remote
from musi.library.db import open_db, run_migrations

DAY = 86400
NOW = 2_000_000_000.0


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    def artist(name):
        return conn.execute("INSERT INTO artists (name) VALUES (?)", (name,)).lastrowid
    a1, a2 = artist("Dua Lipa"), artist("The Weeknd")
    al1 = conn.execute("INSERT INTO albums (artist_id, title) VALUES (?, 'Radical')", (a1,)).lastrowid
    al2 = conn.execute("INSERT INTO albums (artist_id, title) VALUES (?, 'Hours')", (a2,)).lastrowid
    for i in range(30):
        a, al = (a1, al1) if i < 15 else (a2, al2)
        conn.execute("INSERT INTO tracks (album_id, artist_id, path, title, duration) "
                     "VALUES (?, ?, ?, ?, 200)", (al, a, f"/m/{i}.flac", f"Song {i}"))
    # the same song on the server too — the local file must win
    conn.execute("INSERT INTO tracks (album_id, artist_id, path, title, duration) "
                 "VALUES (?, ?, ?, 'Song 0', 200)", (al1, a1, remote.stream_url("s0")))
    conn.commit()
    yield conn
    conn.close()


def _play(db, track_path, when, times=1):
    tid = db.execute("SELECT id FROM tracks WHERE path = ?", (track_path,)).fetchone()[0]
    for k in range(times):
        db.execute("INSERT INTO play_history (track_id, played_at) VALUES (?, ?)",
                   (tid, int(when) + k))
    db.commit()


# ── history mixes ─────────────────────────────────────────────────────────────

def test_on_repeat_is_this_months_most_played(db):
    for i in range(6):
        _play(db, f"/m/{i}.flac", NOW - 5 * DAY, times=10 - i)
    _play(db, "/m/20.flac", NOW - 90 * DAY, times=50)      # old — not this month
    lib = mixes.Library(db)
    m = mixes.on_repeat(db, lib, None, NOW)
    assert [t["path"] for t in m.tracks][:3] == ["/m/0.flac", "/m/1.flac", "/m/2.flac"]
    assert "/m/20.flac" not in [t["path"] for t in m.tracks]


def test_forgotten_favourites_are_loved_then_quiet(db):
    for i in range(20, 26):
        _play(db, f"/m/{i}.flac", NOW - 120 * DAY, times=5)
    _play(db, "/m/20.flac", NOW - 2 * DAY)                  # played again lately
    m = mixes.forgotten(db, mixes.Library(db), None, None, NOW)
    paths = [t["path"] for t in m.tracks]
    assert "/m/21.flac" in paths and "/m/20.flac" not in paths


def test_mixes_without_enough_data_are_not_offered(db):
    assert mixes.on_repeat(db, mixes.Library(db), None, NOW) is None
    assert mixes.forgotten(db, mixes.Library(db), None, None, NOW) is None


def test_daily_mix_holds_still_for_the_day(db):
    lib = mixes.Library(db)
    a = mixes.daily_mix(db, lib, [], NOW)
    b = mixes.daily_mix(db, lib, [], NOW + 60)
    c = mixes.daily_mix(db, lib, [], NOW + 2 * DAY)
    assert [t["path"] for t in a.tracks] == [t["path"] for t in b.tracks]
    assert [t["path"] for t in a.tracks] != [t["path"] for t in c.tracks]


# ── ListenBrainz ──────────────────────────────────────────────────────────────

def test_matching_prefers_local_files_and_ignores_suffixes(db):
    lib = mixes.Library(db)
    assert lib.find("Dua Lipa", "Song 0")["path"] == "/m/0.flac"
    assert lib.find("dua lipa feat. Someone", "Song 1 (Remastered 2024)")["path"] == "/m/1.flac"
    assert lib.find("Nobody", "Song 1") is None


class FakeLB:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if "/playlists/createdfor" in url:
            def pl(kind, mbid, title):
                return {"playlist": {"title": title, "identifier": f"https://listenbrainz.org/playlist/{mbid}",
                        "extension": {"https://musicbrainz.org/doc/jspf#playlist": {
                            "additional_metadata": {"algorithm_metadata": {"source_patch": kind}}}}}}
            return {"playlists": [pl("weekly-jams", "new", "Weekly Jams, this week"),
                                  pl("weekly-jams", "old", "Weekly Jams, last week"),
                                  pl("top-discoveries-of-2025", "x", "Top Discoveries")]}
        if url.endswith("/playlist/new"):
            return {"playlist": {"track": [
                {"creator": "Dua Lipa", "title": f"Song {i}"} for i in range(5)] + [
                {"creator": "Not In Library", "title": "Nope"}]}}
        if "/stats/user/" in url:
            return None                                     # 204: no stats yet
        raise AssertionError(url)


def test_listenbrainz_playlists_become_mixes_from_your_library(db):
    lb = FakeLB()
    made = {m.key: m for m in mixes.build(db, "ilay", NOW, opener=lb)}
    jams = made["weekly-jams"]
    assert [t["path"] for t in jams.tracks] == [f"/m/{i}.flac" for i in range(5)]
    assert "5 of 6 in your library" in jams.subtitle
    assert not any(u.endswith("/playlist/old") for u in lb.urls)   # newest only
    assert "top-discoveries-of-2025" not in made


def test_listenbrainz_down_still_gives_local_mixes(db):
    def down(url):
        raise OSError("offline")
    made = mixes.build(db, "ilay", NOW, opener=down)
    assert [m.key for m in made] == ["daily"]


# ── song radio ────────────────────────────────────────────────────────────────

class FakeServer:
    def search_songs(self, query, count):
        return [{"id": "s0", "title": "Song 0"}]

    def similar_songs(self, sid, count):
        assert sid == "s0"
        return [{"id": "s20", "title": "Song 20", "artist": "The Weeknd"},
                {"id": "zz", "title": "Brand New", "artist": "Elsewhere", "duration": 180}]


def test_song_radio_uses_navidrome_suggestions(db):
    seed = {"path": "/m/0.flac", "title": "Song 0", "artist": "Dua Lipa"}
    r = mixes.song_radio(db, seed, FakeServer())
    paths = [t["path"] for t in r.tracks]
    assert paths[0] == "/m/0.flac"                       # starts with the seed
    assert paths[1] == "/m/20.flac"                      # matched to the local file
    assert remote.stream_url("zz") in paths              # not synced yet: streamed


def test_song_radio_without_a_server_still_plays_something(db):
    r = mixes.song_radio(db, {"path": "/m/0.flac", "title": "Song 0", "artist": "Dua Lipa"})
    assert len(r.tracks) >= 10 and r.tracks[0]["path"] == "/m/0.flac"
    assert len({t["path"] for t in r.tracks}) == len(r.tracks)   # no repeats
