"""Album-level queries behind the Home shelves and the Library grid."""
import pytest

from musi.library.db import open_db, run_migrations
from musi.player import album_queries as q


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "lib.db")
    run_migrations(conn)
    a1 = conn.execute("INSERT INTO artists (name) VALUES ('Alpha')").lastrowid
    a2 = conn.execute("INSERT INTO artists (name) VALUES ('Beta')").lastrowid
    al1 = conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, 'One', 2001)",
        (a1,)).lastrowid
    al2 = conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, 'Two', 2002)",
        (a2,)).lastrowid
    t1 = conn.execute(
        """INSERT INTO tracks (album_id, artist_id, path, title, file_mtime)
           VALUES (?, ?, '/m/1.mp3', 'T1', 100)""", (al1, a1)).lastrowid
    t2 = conn.execute(
        """INSERT INTO tracks (album_id, artist_id, path, title, file_mtime)
           VALUES (?, ?, '/m/2.mp3', 'T2', 200)""", (al2, a2)).lastrowid
    # album One played twice and longest ago; album Two played once, recently
    conn.execute("INSERT INTO play_history (track_id, played_at) VALUES (?, 10)", (t1,))
    conn.execute("INSERT INTO play_history (track_id, played_at) VALUES (?, 20)", (t1,))
    conn.execute("INSERT INTO play_history (track_id, played_at) VALUES (?, 30)", (t2,))
    conn.commit()
    return conn


def test_recently_played_is_newest_first_and_one_row_per_album(db):
    rows = q.recently_played(db)
    assert [r["title"] for r in rows] == ["Two", "One"]


def test_most_played_counts_plays_not_albums(db):
    rows = q.most_played(db)
    assert [r["title"] for r in rows] == ["One", "Two"]


def test_recently_added_uses_file_mtime(db):
    rows = q.recently_added(db)
    assert [r["title"] for r in rows] == ["Two", "One"]


def test_rows_carry_everything_a_tile_needs(db):
    row = q.recently_played(db)[0]
    for col in ("id", "title", "artist", "year", "art_path", "palette",
                "backdrop_path"):
        assert col in row.keys()


def test_limit_is_honoured(db):
    assert len(q.recently_played(db, limit=1)) == 1


def test_empty_history_gives_empty_shelves(tmp_path):
    """A fresh device has zero play_history rows — this is the common case."""
    conn = open_db(tmp_path / "empty.db")
    run_migrations(conn)
    assert q.recently_played(conn) == []
    assert q.most_played(conn) == []


def test_all_albums_is_sorted_by_artist_then_year(db):
    assert [r["title"] for r in q.all_albums(db)] == ["One", "Two"]


def test_all_artists_is_alphabetical(db):
    assert [r["name"] for r in q.all_artists(db)] == ["Alpha", "Beta"]


def test_albums_by_artist_filters(db):
    alpha = [r for r in q.all_artists(db) if r["name"] == "Alpha"][0]
    rows = q.albums_by_artist(db, alpha["id"])
    assert [r["title"] for r in rows] == ["One"]


def test_albums_by_artist_of_an_unknown_id_is_empty(db):
    assert q.albums_by_artist(db, 9999) == []
