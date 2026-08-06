"""Cover Art Archive fetcher — discovery, lookup, download, bookkeeping.

No test here touches the network: the HTTP layer is injected.
"""
import io
import json
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

from pathlib import Path

import pytest
from PIL import Image

from musi.library import art_fetch
from musi.library.db import open_db, run_migrations


def _png_bytes(colour=(200, 30, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def lib(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    music = tmp_path / "music"
    music.mkdir()
    art = tmp_path / "art"
    art.mkdir()

    aid = conn.execute("INSERT INTO artists (name) VALUES ('Daft Punk')").lastrowid
    for title in ("Discovery", "Homework"):
        alb = conn.execute(
            "INSERT INTO albums (artist_id, title, year) VALUES (?, ?, 2001)",
            (aid, title)).lastrowid
        track = music / f"{title}.mp3"
        track.write_bytes(b"not really audio")
        conn.execute(
            "INSERT INTO tracks (album_id, artist_id, path, title, track_number,"
            " duration) VALUES (?,?,?,?,1,100.0)",
            (alb, aid, str(track), f"{title} t1"))
    conn.commit()
    return conn, music, art


# ── discovery ─────────────────────────────────────────────────────────────────

def test_albums_missing_art_finds_albums_with_no_local_source(lib):
    conn, _music, _art = lib
    missing = art_fetch.albums_missing_art(conn)
    assert [m["album"] for m in missing] == ["Discovery", "Homework"]
    assert missing[0]["artist"] == "Daft Punk"


def test_albums_with_a_sidecar_are_not_missing(lib):
    conn, music, _art = lib
    (music / "cover.jpg").write_bytes(_png_bytes())
    # both tracks live in the same folder, so both albums now have a source
    assert art_fetch.albums_missing_art(conn) == []


def test_album_key_matches_the_scanner(lib):
    """Cache files are slug-addressed; a mismatch would write orphaned art."""
    conn, _m, _a = lib
    missing = art_fetch.albums_missing_art(conn)
    assert missing[0]["album_key"] == "Daft Punk::Discovery"


# ── lookup ────────────────────────────────────────────────────────────────────

def test_find_cover_queries_musicbrainz_then_the_archive():
    seen = []

    def fake_get(url, *, accept_image=False, timeout=0):
        seen.append(url)
        if "musicbrainz" in url:
            return json.dumps({"release-groups": [{"id": "mbid-123"}]}).encode()
        return _png_bytes()

    data = art_fetch.find_cover("Daft Punk", "Discovery", get=fake_get)
    assert data == _png_bytes()
    assert "musicbrainz.org" in seen[0]
    assert "coverartarchive.org/release-group/mbid-123" in seen[1]


def test_find_cover_escapes_the_query():
    """Lucene special characters would otherwise break the MusicBrainz query."""
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        return json.dumps({"release-groups": []}).encode()

    art_fetch.find_cover('AC/DC', 'Back in Black "Live"', get=fake_get)
    assert "%22" in seen[0] or "%5C" in seen[0]     # quoted/escaped, not raw


def test_find_cover_returns_none_when_musicbrainz_has_no_match():
    def fake_get(url, **kw):
        return json.dumps({"release-groups": []}).encode()

    assert art_fetch.find_cover("Nobody", "Nothing", get=fake_get) is None


def test_find_cover_returns_none_when_the_archive_has_no_image():
    def fake_get(url, *, accept_image=False, timeout=0):
        if "musicbrainz" in url:
            return json.dumps({"release-groups": [{"id": "x"}]}).encode()
        return None                       # 404 from the archive

    assert art_fetch.find_cover("A", "B", get=fake_get) is None


def test_find_cover_survives_a_network_error():
    def boom(url, **kw):
        raise OSError("no route to host")

    assert art_fetch.find_cover("A", "B", get=boom) is None


# ── run ───────────────────────────────────────────────────────────────────────

def test_fetch_missing_writes_art_and_updates_the_row(lib):
    conn, _music, art = lib

    def fake_get(url, *, accept_image=False, timeout=0):
        if "musicbrainz" in url:
            return json.dumps({"release-groups": [{"id": "m1"}]}).encode()
        return _png_bytes()

    found, total = art_fetch.fetch_missing(conn, art, get=fake_get, pause=0)
    assert (found, total) == (2, 2)

    row = conn.execute(
        "SELECT art_path, backdrop_path, palette FROM albums"
        " WHERE title = 'Discovery'").fetchone()
    assert row["art_path"] and Path(row["art_path"]).exists()
    assert row["backdrop_path"] and Path(row["backdrop_path"]).exists()
    assert json.loads(row["palette"])          # real palette, not empty


def test_fetch_missing_reports_progress(lib):
    conn, _music, art = lib
    seen = []

    def fake_get(url, **kw):
        if "musicbrainz" in url:
            return json.dumps({"release-groups": [{"id": "m1"}]}).encode()
        return _png_bytes()

    art_fetch.fetch_missing(conn, art, get=fake_get, pause=0,
                            progress=lambda done, total, label: seen.append(
                                (done, total, label)))
    assert seen[0][1] == 2
    assert seen[-1][0] == 2
    assert "Discovery" in seen[0][2]


def test_fetch_missing_skips_albums_with_no_match(lib):
    conn, _music, art = lib

    def fake_get(url, **kw):
        if "musicbrainz" in url:
            return json.dumps({"release-groups": []}).encode()
        return None

    found, total = art_fetch.fetch_missing(conn, art, get=fake_get, pause=0)
    assert (found, total) == (0, 2)


def test_fetch_missing_can_be_stopped_midway(lib):
    conn, _music, art = lib

    def fake_get(url, **kw):
        if "musicbrainz" in url:
            return json.dumps({"release-groups": [{"id": "m1"}]}).encode()
        return _png_bytes()

    found, total = art_fetch.fetch_missing(
        conn, art, get=fake_get, pause=0, should_stop=lambda: True)
    assert found == 0


def test_a_fetched_album_is_no_longer_missing(lib):
    conn, _music, art = lib

    def fake_get(url, **kw):
        if "musicbrainz" in url:
            return json.dumps({"release-groups": [{"id": "m1"}]}).encode()
        return _png_bytes()

    art_fetch.fetch_missing(conn, art, get=fake_get, pause=0)
    assert art_fetch.albums_missing_art(conn, art) == []
    # ...and a second run has nothing left to do, so MusicBrainz is left alone
    assert art_fetch.fetch_missing(conn, art, get=fake_get, pause=0) == (0, 0)
