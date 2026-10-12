"""Album-level queries for the Home shelves and the Library grid.

play_history stores one row per *track* play. Every shelf is a shelf of
albums, so all three history queries group to album_id. No schema change is
needed for any of this.

Callers run these in on_enter — never in draw. tests/test_draw_loop_cost.py
pins zero SQL after the first frame.
"""
from __future__ import annotations

_COLS = """al.id, al.title, ar.name AS artist, al.year,
           al.art_path, al.palette, al.backdrop_path"""


def recently_played(db, limit: int = 12) -> list:
    return db.execute(
        f"""SELECT {_COLS}, MAX(ph.played_at) AS last_played
            FROM play_history ph
            JOIN tracks  t  ON t.id  = ph.track_id
            JOIN albums  al ON al.id = t.album_id
            JOIN artists ar ON ar.id = al.artist_id
            GROUP BY al.id
            ORDER BY last_played DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()


def most_played(db, limit: int = 12) -> list:
    return db.execute(
        f"""SELECT {_COLS}, COUNT(*) AS plays, MAX(ph.played_at) AS last_played
            FROM play_history ph
            JOIN tracks  t  ON t.id  = ph.track_id
            JOIN albums  al ON al.id = t.album_id
            JOIN artists ar ON ar.id = al.artist_id
            GROUP BY al.id
            ORDER BY plays DESC, last_played DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()


def recently_added(db, limit: int = 12) -> list:
    """Newest music on the device, by file mtime — works with no play history.

    The inner JOIN tracks deliberately drops albums with no tracks: they have
    no file_mtime to sort by and nothing to play on a "New in your library"
    shelf. all_albums() does not join tracks and *will* list such an album —
    that difference is intended, not a bug.
    """
    return db.execute(
        f"""SELECT {_COLS}, MAX(t.file_mtime) AS added
            FROM albums  al
            JOIN tracks  t  ON t.album_id = al.id
            JOIN artists ar ON ar.id = al.artist_id
            GROUP BY al.id
            ORDER BY added DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()


def all_albums(db) -> list:
    return db.execute(
        f"""SELECT {_COLS}
            FROM albums  al
            JOIN artists ar ON ar.id = al.artist_id
            ORDER BY ar.name COLLATE NOCASE, al.year, al.title COLLATE NOCASE"""
    ).fetchall()


def all_artists(db) -> list:
    return db.execute(
        "SELECT id, name FROM artists ORDER BY name COLLATE NOCASE"
    ).fetchall()


def albums_by_artist(db, artist_id: int) -> list:
    """One artist's albums — the Library artist drill-in."""
    return db.execute(
        f"""SELECT {_COLS}
            FROM albums  al
            JOIN artists ar ON ar.id = al.artist_id
            WHERE al.artist_id = ?
            ORDER BY al.year, al.title COLLATE NOCASE""",
        (artist_id,),
    ).fetchall()


# ── the artist page ───────────────────────────────────────────────────────────

def artist_albums(db, artist_id: int) -> list:
    """An artist's albums, newest first, with each one's song count."""
    return db.execute(
        f"""SELECT {_COLS}, COUNT(t.id) AS songs
            FROM albums  al
            JOIN artists ar ON ar.id = al.artist_id
            LEFT JOIN tracks t ON t.album_id = al.id
            WHERE al.artist_id = ?
            GROUP BY al.id
            ORDER BY al.year IS NULL, al.year DESC, al.title COLLATE NOCASE""",
        (artist_id,),
    ).fetchall()


def artist_tracks(db, artist_id: int) -> list:
    """Every song on the artist's albums, album by album (oldest first) —
    what Play / Shuffle on the artist page queue up."""
    return db.execute(
        """SELECT t.id, t.path, t.title, t.duration, ar.name AS artist
           FROM tracks  t
           JOIN albums  al ON al.id = t.album_id
           JOIN artists ar ON ar.id = al.artist_id
           WHERE al.artist_id = ?
           ORDER BY al.year, al.title COLLATE NOCASE, t.disc_number, t.track_number""",
        (artist_id,),
    ).fetchall()


def artist_top_tracks(db, artist_id: int, limit: int = 5) -> list:
    """The artist's songs you've played most (needs play history)."""
    return db.execute(
        """SELECT t.id, t.path, t.title, t.duration, al.title AS album,
                  al.art_path, COUNT(*) AS plays
           FROM play_history ph
           JOIN tracks  t  ON t.id  = ph.track_id
           JOIN albums  al ON al.id = t.album_id
           WHERE al.artist_id = ?
           GROUP BY t.id
           ORDER BY plays DESC, MAX(ph.played_at) DESC
           LIMIT ?""",
        (artist_id, limit),
    ).fetchall()


def ids_for_track(db, path: str, artist: str = "", album: str = "") -> tuple[int, int] | None:
    """(album_id, artist_id) of what's playing — by its path, else by the
    album artist + album names. None when it isn't in the library (radio,
    AirPlay, a file outside it)."""
    if path:
        row = db.execute(
            """SELECT t.album_id, al.artist_id FROM tracks t
               JOIN albums al ON al.id = t.album_id WHERE t.path = ?""",
            (path,)).fetchone()
        if row:
            return row[0], row[1]
    if artist and album:
        row = db.execute(
            """SELECT al.id, al.artist_id FROM albums al
               JOIN artists ar ON ar.id = al.artist_id
               WHERE ar.name = ? AND al.title = ?""",
            (artist, album)).fetchone()
        if row:
            return row[0], row[1]
    return None


def artist_id_by_name(db, name: str) -> int | None:
    row = db.execute("SELECT id FROM artists WHERE name = ?", (name,)).fetchone() if name else None
    return row[0] if row else None
