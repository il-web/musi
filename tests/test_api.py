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

# A minimal but valid MPEG1 Layer3 stream mutagen can parse and tag
_MP3_BYTES = (b"\xff\xfb\x10\xc0" + b"\x00" * 100) * 20


@pytest.fixture
def client_factory(tmp_path):
    """Build a test client over the seeded library, overriding app kwargs.

    Each call returns a client with its OWN app, so per-app state (the login
    throttle) doesn't leak between assertions in a single test.
    """
    def make(**kwargs):
        (tmp_path / "music").mkdir(exist_ok=True)
        (tmp_path / "art").mkdir(exist_ok=True)
        opts = {"token_provider": lambda: TOKEN, "cors_origins": {ORIGIN}}
        opts.update(kwargs)
        app = create_app(tmp_path / "music", tmp_path / "library.db",
                         tmp_path / "art", **opts)
        app.testing = True
        c = app.test_client()
        c.music_root = tmp_path / "music"
        c.art_dir    = tmp_path / "art"
        c.db_path    = tmp_path / "library.db"
        return c
    return make


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    art   = tmp_path / "art"
    music.mkdir()
    art.mkdir()
    db = tmp_path / "library.db"

    conn = open_db(db)
    run_migrations(conn)
    art_file = art / "aaaa_thumb.jpg"
    art_file.write_bytes(b"\xff\xd8\xff-fake-jpeg")
    (art / "aaaa_palette.json").write_text("[]")
    artist = conn.execute(
        "INSERT INTO artists (name) VALUES ('Artist')").lastrowid
    album = conn.execute(
        "INSERT INTO albums (artist_id, title, year, art_path) VALUES (?,?,?,?)",
        (artist, "Album", 2001, str(art_file))).lastrowid
    for n, title in enumerate(("One", "Two"), start=1):
        track_file = music / f"{title.lower()}.mp3"
        track_file.write_bytes(_MP3_BYTES)
        conn.execute(
            "INSERT INTO tracks (album_id, artist_id, path, title, track_number, duration)"
            " VALUES (?,?,?,?,?,?)",
            (album, artist, str(track_file), title, n, 60.0 + n))
    conn.commit()
    conn.close()

    app = create_app(music, db, art,
                     token_provider=lambda: TOKEN,
                     cors_origins={ORIGIN})
    app.testing = True
    c = app.test_client()
    c.music_root = music          # for upload/delete assertions
    c.art_dir    = art
    c.db_path    = db
    return c


# ── auth ──────────────────────────────────────────────────────────────────────

def test_api_requires_token(client):
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/albums",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_token_comparison_ignores_case_and_dashes(client):
    """The token is typed by hand off the device screen, so 'k7rm-92fq' and
    'K7RM92FQ' must both work."""
    from musi.api import auth
    canon = auth.normalize(TOKEN)
    for variant in (canon, canon.lower(), auth.format_token(canon),
                    auth.format_token(canon).lower()):
        r = client.get("/api/v1/status",
                       headers={"Authorization": f"Bearer {variant}"})
        assert r.status_code == 200, variant


def test_repeated_wrong_tokens_get_throttled(client):
    """The 8-char token is only safe because guessing is rate limited."""
    from musi.api.server import FAIL_FREE
    bad = {"Authorization": "Bearer WRNGWRNG"}
    for _ in range(FAIL_FREE):
        assert client.get("/api/v1/status", headers=bad).status_code == 401
    r = client.get("/api/v1/status", headers=bad)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    # the throttle must not lock out a caller holding the right token
    assert client.get("/api/v1/status", headers=AUTH).status_code == 429


def test_empty_token_file_authenticates_nobody(tmp_path, client_factory):
    """normalize() returns '' for junk and compare_digest('','') is True — a
    missing or corrupt token file must not open the device to everyone."""
    c = client_factory(token_provider=lambda: "")
    assert c.get("/api/v1/status").status_code == 401
    assert c.get("/api/v1/status",
                 headers={"Authorization": "Bearer "}).status_code == 401
    assert c.get("/api/v1/status",
                 headers={"Authorization": "Bearer !!!"}).status_code == 401


def test_only_the_page_itself_is_public(client):
    """/ is public because it is the form that asks for the token; everything
    it calls needs one. 'On the LAN' includes every other device on the WiFi."""
    page = client.get("/")
    assert page.status_code == 200
    assert b"Enter the device token" in page.data

    assert client.get("/stats").status_code == 401
    assert client.get("/stats", headers=AUTH).get_json() == {"tracks": 2}
    assert client.post("/upload", data={
        "file": (io.BytesIO(b"ID3"), "sneaky.mp3")}).status_code == 401
    assert not (client.music_root / "sneaky.mp3").exists()


def test_page_does_not_leak_the_token(client):
    """The public page must not embed the token it is asking the user for."""
    assert TOKEN.encode() not in client.get("/").data


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


def test_album_art_refuses_paths_outside_the_cache(client, tmp_path):
    """The art route reads whatever path the DB names. If anything ever writes
    an art_path pointing elsewhere, it must not become a file-read primitive."""
    secret = tmp_path / "secret.txt"
    secret.write_text("ssh-private-key")
    aid = client.get("/api/v1/albums", headers=AUTH).get_json()["albums"][0]["id"]

    conn = open_db(client.db_path)
    conn.execute("UPDATE albums SET art_path = ? WHERE id = ?", (str(secret), aid))
    conn.commit()
    conn.close()

    r = client.get(f"/api/v1/albums/{aid}/art", headers=AUTH)
    assert r.status_code == 404
    assert b"ssh-private-key" not in r.data


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
    r = client.post("/upload", headers=AUTH, data={
        "file": (io.BytesIO(b"ID3-not-really-audio"), "song.mp3"),
    })
    assert r.get_json()["status"] == "ok"
    assert (client.music_root / "song.mp3").read_bytes() == b"ID3-not-really-audio"

    # same name again → skipped
    r = client.post("/upload", headers=AUTH, data={
        "file": (io.BytesIO(b"ID3-other"), "song.mp3"),
    })
    assert r.get_json()["status"] == "skipped"

    # non-audio → skipped
    r = client.post("/upload", headers=AUTH, data={
        "file": (io.BytesIO(b"hi"), "notes.txt"),
    })
    assert r.get_json()["status"] == "skipped"


def test_upload_refused_while_storage_locked(client, monkeypatch):
    monkeypatch.setattr("musi.api.server._storage_locked", lambda: True)
    r = client.post("/upload", headers=AUTH, data={
        "file": (io.BytesIO(b"ID3"), "locked.mp3"),
    })
    assert r.status_code == 423
    assert not (client.music_root / "locked.mp3").exists()


def test_cors_origins_file(client, tmp_path, monkeypatch):
    from musi.api.server import _cors_origins
    origins_file = tmp_path / "api-origins"
    origins_file.write_text("# site origins\nhttps://musi.example/\n\n")
    monkeypatch.setenv("MUSI_API_ORIGINS_PATH", str(origins_file))
    origins = _cors_origins()
    assert "https://musi.example" in origins          # trailing slash stripped
    assert "# site origins" not in origins


# ── authenticated writes (pack 2) ─────────────────────────────────────────────

def _album_id(client):
    return client.get("/api/v1/albums", headers=AUTH).get_json()["albums"][0]["id"]


def _track_ids(client):
    aid = _album_id(client)
    d = client.get(f"/api/v1/albums/{aid}", headers=AUTH).get_json()
    return aid, [t["id"] for t in d["tracks"]]


def test_api_upload(client):
    r = client.post("/api/v1/upload", headers=AUTH, data={
        "file": (io.BytesIO(_MP3_BYTES), "three.mp3"),
    })
    assert r.get_json()["status"] == "ok"
    assert (client.music_root / "three.mp3").exists()
    # and it is token-gated, unlike the legacy route
    assert client.post("/api/v1/upload", data={
        "file": (io.BytesIO(b"x"), "four.mp3"),
    }).status_code == 401


def test_delete_track(client):
    _, (tid, _tid2) = _track_ids(client)
    assert client.delete(f"/api/v1/tracks/{tid}",
                         headers=AUTH).get_json()["status"] == "ok"
    assert not (client.music_root / "one.mp3").exists()
    assert (client.music_root / "two.mp3").exists()          # untouched
    _, remaining = _track_ids(client)
    assert remaining == [_tid2]
    assert client.delete(f"/api/v1/tracks/{tid}",
                         headers=AUTH).status_code == 404    # already gone


def test_delete_album(client):
    aid = _album_id(client)
    r = client.delete(f"/api/v1/albums/{aid}", headers=AUTH)
    assert r.get_json() == {"status": "ok", "removed_tracks": 2}
    assert not (client.music_root / "one.mp3").exists()
    assert not (client.music_root / "two.mp3").exists()
    assert not (client.art_dir / "aaaa_thumb.jpg").exists()      # art cache
    assert not (client.art_dir / "aaaa_palette.json").exists()   # + sidecar
    assert client.get("/api/v1/albums", headers=AUTH).get_json()["albums"] == []
    assert client.delete(f"/api/v1/albums/{aid}", headers=AUTH).status_code == 404


def test_patch_track(client):
    from musi.library.tags import read_tags
    _, (tid, _) = _track_ids(client)
    r = client.patch(f"/api/v1/tracks/{tid}", headers=AUTH,
                     json={"title": "Renamed", "year": 2020, "track_number": 9})
    assert r.get_json()["status"] == "ok"
    tags = read_tags(client.music_root / "one.mp3")   # real file tags changed
    assert (tags.title, tags.year, tags.track_number) == ("Renamed", 2020, 9)
    _, tracks = _track_ids(client)                    # DB mirrored immediately
    d = client.get(f"/api/v1/albums/{_album_id(client)}", headers=AUTH).get_json()
    renamed = [t for t in d["tracks"] if t["id"] == tid][0]
    assert renamed["title"] == "Renamed"
    assert renamed["track_number"] == 9


def test_patch_track_validation(client):
    _, (tid, _) = _track_ids(client)
    assert client.patch(f"/api/v1/tracks/{tid}", headers=AUTH,
                        json={"genre": "x"}).status_code == 400
    assert client.patch(f"/api/v1/tracks/{tid}", headers=AUTH,
                        json={"year": "soon"}).status_code == 400
    assert client.patch(f"/api/v1/tracks/{tid}", headers=AUTH).status_code == 400
    assert client.patch("/api/v1/tracks/999", headers=AUTH,
                        json={"title": "x"}).status_code == 404


def test_put_album_art(client):
    from PIL import Image
    aid = _album_id(client)
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 90)).save(buf, "PNG")
    r = client.put(f"/api/v1/albums/{aid}/art", headers=AUTH,
                   data=buf.getvalue(), content_type="image/png")
    assert r.get_json()["status"] == "ok"
    art = client.get(f"/api/v1/albums/{aid}/art", headers=AUTH)
    assert art.status_code == 200
    assert art.data.startswith(b"\xff\xd8\xff")       # regenerated JPEG thumb

    # curl --data-binary default content type must not eat the body
    r = client.put(f"/api/v1/albums/{aid}/art", headers=AUTH,
                   data=buf.getvalue(),
                   content_type="application/x-www-form-urlencoded")
    assert r.get_json()["status"] == "ok"

    assert client.put(f"/api/v1/albums/{aid}/art", headers=AUTH,
                      data=b"not an image").status_code == 400
    assert client.put("/api/v1/albums/999/art", headers=AUTH,
                      data=buf.getvalue()).status_code == 404


def test_art_override_survives_rescan(client, tmp_path):
    """A rescan must reuse (not regenerate) the overridden cache files."""
    from musi.library.art import override_art, process_art
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 200, 40)).save(buf, "PNG")
    thumb, _, _ = override_art(buf.getvalue(), client.art_dir, "Artist::Album")
    override_bytes = thumb.read_bytes()
    # what _get_or_create_album calls when recreating the row on rescan
    thumb2, _, _ = process_art(client.music_root / "one.mp3",
                               client.art_dir, "Artist::Album")
    assert thumb2 == thumb
    assert thumb2.read_bytes() == override_bytes


def test_all_writes_blocked_while_locked(client, monkeypatch):
    monkeypatch.setattr("musi.api.server._storage_locked", lambda: True)
    aid = _album_id(client)
    _, (tid, _) = _track_ids(client)
    assert client.post("/api/v1/upload", headers=AUTH, data={
        "file": (io.BytesIO(b"x"), "z.mp3")}).status_code == 423
    assert client.delete(f"/api/v1/tracks/{tid}", headers=AUTH).status_code == 423
    assert client.delete(f"/api/v1/albums/{aid}", headers=AUTH).status_code == 423
    assert client.patch(f"/api/v1/tracks/{tid}", headers=AUTH,
                        json={"title": "x"}).status_code == 423
    assert client.put(f"/api/v1/albums/{aid}/art", headers=AUTH,
                      data=b"img").status_code == 423
    # reads still work while locked
    assert client.get("/api/v1/albums", headers=AUTH).status_code == 200
    # and nothing was actually deleted
    assert (client.music_root / "one.mp3").exists()
