"""Mirror a music server's catalog into the local library.

Only metadata is copied — audio streams on demand. Server songs become rows in
the same tracks/albums/artists tables the scanner fills, so Browse, Search,
albums, play history and Favourites all work on them unchanged; their ``path``
is a stream URL (see remote.py), which is what the UI's cloud tag keys off.

Rules:
  - Local wins. A server song whose album artist + album + title matches a
    local track is skipped, so an album you own on both sides isn't doubled.
  - Albums merge by (album artist, title), exactly as the scanner keys them:
    an album that is half local, half server shows as one album.
  - The sync owns every row with a stream URL and nothing else. Songs gone
    from the server are removed; the scanner, in turn, never touches them.
  - Cover art comes from the server (getCoverArt) through the same pipeline
    as local art: thumb, blurred backdrop, palette.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

from musi.library import art, remote
from musi.library.subsonic import Client, SubsonicError, update_settings

BATCH = 200

# Background sync (the player calls maybe_auto_sync about once a minute)
AUTO_EVERY_S = 6 * 3600     # re-sync this often
AUTO_RETRY_S = 30 * 60      # after a failed attempt (offline, server down)
AUTO_FIRST_S = 120          # after boot: let playback settle first

log = logging.getLogger(__name__)

Progress = Optional[Callable[[str, int, int], None]]   # (phase, done, total)


def sync(client: Client, conn: sqlite3.Connection, art_dir: Path, *,
         progress: Progress = None,
         should_stop: Callable[[], bool] = lambda: False) -> dict:
    """Bring the library in line with the server. Returns stats:
    added, updated, removed, skipped_local, art."""
    stats = {"added": 0, "updated": 0, "removed": 0, "skipped_local": 0, "art": 0}
    report = progress or (lambda *a: None)

    # ── 1. what the server has ────────────────────────────────────────────────
    report("albums", 0, 0)
    albums = {a["id"]: a for a in client.albums()}
    report("songs", 0, len(albums))
    songs = list(client.all_songs())
    if not songs and albums:
        # search3 with an empty query isn't universal — walk album by album
        for i, album_id in enumerate(albums):
            if should_stop():
                return stats
            songs.extend(client.album_songs(album_id))
            report("songs", i + 1, len(albums))

    # ── 2. what we already have ──────────────────────────────────────────────
    local_keys = {
        _key(r["artist"], r["album"], r["title"])
        for r in conn.execute(
            """SELECT ar.name AS artist, al.title AS album, t.title
               FROM tracks t JOIN albums al ON al.id = t.album_id
               JOIN artists ar ON ar.id = al.artist_id
               WHERE t.path NOT LIKE 'http%'""")
    }
    known = {r["path"] for r in conn.execute(
        "SELECT path FROM tracks WHERE path LIKE 'http%'")}

    # ── 3. upsert server songs ────────────────────────────────────────────────
    seen: set[str] = set()
    for i, song in enumerate(songs):
        if should_stop():
            conn.commit()
            return stats
        album = albums.get(song.get("albumId"), {})
        album_artist = (album.get("artist") or song.get("artist")
                        or "Unknown Artist")
        album_title = song.get("album") or album.get("name") or "Unknown Album"
        title = song.get("title") or "Untitled"

        if _key(album_artist, album_title, title) in local_keys:
            stats["skipped_local"] += 1
            continue

        path = remote.stream_url(str(song["id"]))
        seen.add(path)
        artist_id = _artist(conn, album_artist)
        album_id = _album(conn, artist_id, album_title,
                          album.get("year") or song.get("year"))
        conn.execute(
            """INSERT INTO tracks (album_id, artist_id, path, title,
                                   track_number, disc_number, duration, file_mtime)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(path) DO UPDATE SET
                   album_id = excluded.album_id, artist_id = excluded.artist_id,
                   title = excluded.title, track_number = excluded.track_number,
                   disc_number = excluded.disc_number, duration = excluded.duration""",
            (album_id, artist_id, path, title, song.get("track"),
             song.get("discNumber") or 1, song.get("duration")),
        )
        stats["updated" if path in known else "added"] += 1
        if (i + 1) % BATCH == 0:
            conn.commit()
            report("songs", i + 1, len(songs))
    conn.commit()

    # ── 4. drop what the server no longer has ────────────────────────────────
    gone = known - seen
    for path in gone:
        _remove(conn, path)
    stats["removed"] = len(gone)
    conn.commit()

    # ── 5. cover art for albums that have none yet ───────────────────────────
    cover_for = _cover_ids(songs, albums)
    todo = conn.execute(
        """SELECT al.id, al.title, ar.name AS artist,
                  MIN(t.path) AS probe
           FROM albums al JOIN artists ar ON ar.id = al.artist_id
           JOIN tracks t ON t.album_id = al.id
           WHERE al.art_path IS NULL
           GROUP BY al.id""").fetchall()
    for i, row in enumerate(todo):
        if should_stop():
            break
        report("art", i + 1, len(todo))
        album_key = f"{row['artist']}::{row['title']}"
        cover_id = cover_for.get((row["artist"].lower(), row["title"].lower()))
        try:
            thumb, backdrop, palette = _album_art(client, cover_id, art_dir, album_key)
        except Exception:
            log.warning("art for %s failed", album_key, exc_info=True)
            continue
        conn.execute(
            "UPDATE albums SET art_path = ?, backdrop_path = ?, palette = ? WHERE id = ?",
            (str(thumb), str(backdrop), json.dumps(palette), row["id"]))
        stats["art"] += 1
        if (i + 1) % 20 == 0:
            conn.commit()
    conn.commit()

    count = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE path LIKE 'http%'").fetchone()[0]
    update_settings(last_sync=int(time.time()), track_count=count, last_error=None)
    return stats


def remove_all(conn: sqlite3.Connection) -> int:
    """Forget every server track (used when the server is signed out)."""
    paths = [r[0] for r in conn.execute(
        "SELECT path FROM tracks WHERE path LIKE 'http%'")]
    for p in paths:
        _remove(conn, p)
    conn.commit()
    return len(paths)


# ── helpers ───────────────────────────────────────────────────────────────────

def _key(artist: str, album: str, title: str) -> tuple[str, str, str]:
    return (artist or "").strip().lower(), (album or "").strip().lower(), \
        (title or "").strip().lower()


def _artist(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM artists WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO artists (name) VALUES (?)", (name,)).lastrowid


def _album(conn: sqlite3.Connection, artist_id: int, title: str,
           year: int | None) -> int:
    row = conn.execute("SELECT id FROM albums WHERE artist_id = ? AND title = ?",
                       (artist_id, title)).fetchone()
    if row:
        return row[0]
    # art is filled in by phase 5, after every track is in
    return conn.execute(
        "INSERT INTO albums (artist_id, title, year) VALUES (?, ?, ?)",
        (artist_id, title, year)).lastrowid


def _remove(conn: sqlite3.Connection, path: str) -> None:
    """Delete one track and whatever it leaves orphaned. Play history goes
    first: it references the track, and foreign keys are enforced."""
    conn.execute(
        "DELETE FROM play_history WHERE track_id IN (SELECT id FROM tracks WHERE path = ?)",
        (path,))
    conn.execute("DELETE FROM tracks WHERE path = ?", (path,))
    conn.execute("DELETE FROM albums WHERE id NOT IN (SELECT DISTINCT album_id FROM tracks)")
    conn.execute("DELETE FROM artists WHERE id NOT IN (SELECT DISTINCT artist_id FROM tracks)")


def _cover_ids(songs: list[dict], albums: dict) -> dict:
    """(album artist, album title) lowercased → the server's cover art id."""
    out: dict = {}
    for a in albums.values():
        if a.get("coverArt"):
            out[((a.get("artist") or "").lower(), (a.get("name") or "").lower())] = a["coverArt"]
    for s in songs:
        album = albums.get(s.get("albumId"), {})
        k = ((album.get("artist") or s.get("artist") or "").lower(),
             (s.get("album") or "").lower())
        if s.get("coverArt") and k not in out:
            out[k] = s["coverArt"]
    return out


def _album_art(client: Client, cover_id: str | None, art_dir: Path, album_key: str):
    """Server cover through the normal art pipeline — or the generated
    gradient every art-less local album gets, when the server has none."""
    if cover_id:
        try:
            return art.override_art(client.cover_art(cover_id), art_dir, album_key)
        except SubsonicError:
            log.info("no cover from server for %s", album_key)
    # process_art finds no embedded/sidecar art at a path that isn't there,
    # and falls back to the deterministic gradient
    return art.process_art(art_dir / "__remote__", art_dir, album_key)


# ── background job ────────────────────────────────────────────────────────────

class SyncJob:
    """One sync at a time, on a worker thread, with state a UI can poll.

    Each process (the player, the API service) has its own; they write through
    separate SQLite connections, which WAL mode is fine with.
    """

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self.running = False
        self.phase = ""
        self.done = 0
        self.total = 0
        self.error = ""
        self.stats: dict | None = None
        self._thread = None

    def start(self, db_path: Path, art_dir: Path,
              on_done: Callable[[], None] | None = None) -> bool:
        """Start a sync; False if one is already running or no server is set."""
        import threading
        from musi.library.db import open_db
        from musi.library.subsonic import Client

        with self._lock:
            if self.running:
                return False
            client = Client.from_settings()
            if client is None:
                self.error = "no server set up"
                return False
            self.running, self.error, self.stats = True, "", None
            self.phase, self.done, self.total = "connecting", 0, 0

        def report(phase: str, done: int, total: int) -> None:
            self.phase, self.done, self.total = phase, done, total

        def work() -> None:
            conn = None
            _lower_priority()
            try:
                conn = open_db(db_path)
                self.stats = sync(client, conn, art_dir, progress=report)
            except Exception as exc:
                self.error = str(exc) or exc.__class__.__name__
                log.warning("subsonic sync failed", exc_info=True)
                try:
                    update_settings(last_error=self.error)
                except OSError:
                    pass
            finally:
                if conn is not None:
                    conn.close()
                self.running = False
                if on_done:
                    on_done()

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        return True

    def join(self, timeout: float = 30.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


job = SyncJob()     # this process's sync


def _lower_priority() -> None:
    """Nice this worker thread (Linux: threads are tasks with their own
    priority) so a big sync never takes CPU from the render loop."""
    import os
    import threading
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError):
        pass


def auto_due(settings: dict | None, now: float, uptime: float) -> bool:
    """Is a background sync due? Never during the first minutes after boot;
    every AUTO_EVERY_S after the last success; failures retry sooner."""
    if not settings or settings.get("auto_sync") is False or uptime < AUTO_FIRST_S:
        return False
    since_sync = now - (settings.get("last_sync") or 0)
    since_try = now - (settings.get("last_auto_try") or 0)
    return since_sync >= AUTO_EVERY_S and since_try >= AUTO_RETRY_S


def maybe_auto_sync(db_path: Path, art_dir: Path, uptime: float,
                    now: float | None = None) -> bool:
    """Start a background sync if one is due. Returns True if it started."""
    from musi.library.subsonic import load_settings
    now = time.time() if now is None else now
    if job.running or not auto_due(load_settings(), now, uptime):
        return False
    update_settings(last_auto_try=int(now))
    return job.start(db_path, art_dir)
