"""Device API tests — Flask test client over a seeded temp library."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from musi.api.server import create_app
from musi.library.db import open_db, run_migrations

TOKEN  = "test-token"
ORIGIN = "https://site.example"
AUTH   = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    art   = tmp_path / "art"
    music.mkdir()
    art.mkdir()
    db = tmp_path / "library.db"

    conn = open_db(db)
    run_migrations(conn)
    art_file = art / "thumb.jpg"
    art_file.write_bytes(b"\xff\xd8\xff-fake-jpeg")
    artist = conn.execute(
        "INSERT INTO artists (name) VALUES ('Artist')").lastrowid
    album = conn.execute(
        "INSERT INTO albums (artist_id, title, year, art_path) VALUES (?,?,?,?)",
        (artist, "Album", 2001, str(art_file))).lastrowid
    for n, title in enumerate(("One", "Two"), start=1):
        conn.execute(
            "INSERT INTO tracks (album_id, artist_id, path, title, track_number, duration)"
            " VALUES (?,?,?,?,?,?)",
            (album, artist, f"a/{n}.mp3", title, n, 60.0 + n))
    conn.commit()
    conn.close()

    app = create_app(music, db, art,
                     token_provider=lambda: TOKEN,
                     cors_origins={ORIGIN})
    app.testing = True
    c = app.test_client()
    c.music_root = music          # for the upload test
    return c


# ── auth ──────────────────────────────────────────────────────────────────────

def test_api_requires_token(client):
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/albums",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_legacy_routes_stay_open(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"WiFi Transfer" in page.data
    assert client.get("/stats").get_json() == {"tracks": 2}


# ── read endpoints ────────────────────────────────────────────────────────────

def test_status(client):
    d = client.get("/api/v1/status", headers=AUTH).get_json()
    assert d["counts"] == {"artists": 1, "albums": 1, "tracks": 2}
    assert d["storage"]["total"] > 0
    assert d["storage_locked"] is False
    assert isinstance(d["version"], str)
    assert d["uptime_s"] >= 0


def test_albums_list(client):
    d = client.get("/api/v1/albums", headers=AUTH).get_json()
    assert len(d["albums"]) == 1
    a = d["albums"][0]
    assert a["title"] == "Album"
    assert a["artist"] == "Artist"
    assert a["year"] == 2001
    assert a["track_count"] == 2
    assert a["art"] == f"/api/v1/albums/{a['id']}/art"


def test_album_detail(client):
    aid = client.get("/api/v1/albums", headers=AUTH).get_json()["albums"][0]["id"]
    d = client.get(f"/api/v1/albums/{aid}", headers=AUTH).get_json()
    assert d["title"] == "Album"
    assert [t["title"] for t in d["tracks"]] == ["One", "Two"]
    assert d["tracks"][0]["track_number"] == 1


def test_album_not_found(client):
    assert client.get("/api/v1/albums/999", headers=AUTH).status_code == 404
    assert client.get("/api/v1/albums/999/art", headers=AUTH).status_code == 404


def test_album_art(client):
    aid = client.get("/api/v1/albums", headers=AUTH).get_json()["albums"][0]["id"]
    r = client.get(f"/api/v1/albums/{aid}/art", headers=AUTH)
    assert r.status_code == 200
    assert r.data.startswith(b"\xff\xd8\xff")


# ── CORS ──────────────────────────────────────────────────────────────────────

def test_cors_preflight_needs_no_token(client):
    r = client.options("/api/v1/status", headers={"Origin": ORIGIN})
    assert r.status_code < 400
    assert r.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"]


def test_cors_on_response(client):
    r = client.get("/api/v1/status", headers={**AUTH, "Origin": ORIGIN})
    assert r.headers["Access-Control-Allow-Origin"] == ORIGIN


def test_cors_unknown_origin(client):
    r = client.get("/api/v1/status",
                   headers={**AUTH, "Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


# ── legacy upload ─────────────────────────────────────────────────────────────

def test_upload(client):
    r = client.post("/upload", data={
        "file": (io.BytesIO(b"ID3-not-really-audio"), "song.mp3"),
    })
    assert r.get_json()["status"] == "ok"
    assert (client.music_root / "song.mp3").read_bytes() == b"ID3-not-really-audio"

    # same name again → skipped
    r = client.post("/upload", data={
        "file": (io.BytesIO(b"ID3-other"), "song.mp3"),
    })
    assert r.get_json()["status"] == "skipped"

    # non-audio → skipped
    r = client.post("/upload", data={
        "file": (io.BytesIO(b"hi"), "notes.txt"),
    })
    assert r.get_json()["status"] == "skipped"


def test_upload_refused_while_storage_locked(client, monkeypatch):
    monkeypatch.setattr("musi.api.server._storage_locked", lambda: True)
    r = client.post("/upload", data={
        "file": (io.BytesIO(b"ID3"), "locked.mp3"),
    })
    assert r.status_code == 423
    assert not (client.music_root / "locked.mp3").exists()
