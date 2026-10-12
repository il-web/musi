"""Music library scanner.

Walks a directory tree, reads tags, processes album art, and writes
everything into the SQLite database. Uses file mtime to skip unchanged
tracks on re-scans.
"""

import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from musi.library import art, quality
from musi.library.art import process_art
from musi.library.tags import TrackTags, is_audio_file, read_tags

BATCH_SIZE = 50  # commit to DB every N tracks


def scan(
    music_root: Path,
    art_dir: Path,
    conn: sqlite3.Connection,
    *,
    force: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Scan music_root and sync the database.

    Args:
        music_root: Root folder to walk.
        art_dir:    Where to store generated art assets.
        conn:       Open database connection (migrations already applied).
        force:      Re-process every file even if mtime unchanged.
        progress:   Optional callback(current, total, filename).

    Returns:
        Stats dict with keys: added, updated, skipped, failed, removed.
    """
    stats = {"added": 0, "updated": 0, "skipped": 0, "failed": 0, "removed": 0}

    # ── 1. collect files on disk ──────────────────────────────────────────────
    print(f"Scanning {music_root} ...")
    disk: dict[str, Path] = {
        str(p): p
        for p in music_root.rglob("*")
        if is_audio_file(p)
    }
    print(f"  Found {len(disk)} audio files on disk")

    # ── 2. remove tracks that disappeared from disk ───────────────────────────
    # Server-streamed tracks (stream URLs, see remote.py) are never on disk —
    # they belong to subsonic_sync, so the scanner must not even see them.
    db_rows = {
        row["path"]: row["file_mtime"]
        for row in conn.execute(
            "SELECT path, file_mtime FROM tracks WHERE path NOT LIKE 'http%'")
    }
    removed = set(db_rows) - set(disk)
    for path_str in removed:
        _remove_track(conn, path_str)
        stats["removed"] += 1
    if removed:
        conn.commit()
        print(f"  Removed {len(removed)} deleted tracks")

    # ── 3. determine what needs processing ───────────────────────────────────
    pending: list[tuple[Path, float]] = []
    for path_str, path in disk.items():
        mtime = path.stat().st_mtime
        if not force and path_str in db_rows and abs(db_rows[path_str] - mtime) < 1.0:
            stats["skipped"] += 1
        else:
            pending.append((path, mtime))

    total = len(pending)
    print(f"  {stats['skipped']} unchanged  |  {total} to process")

    # ── 4. process pending files ──────────────────────────────────────────────
    for i, (path, mtime) in enumerate(pending):
        if progress:
            progress(i + 1, total, path.name)

        tags = read_tags(path)
        if tags is None:
            print(f"  [skip] unreadable: {path.name}")
            stats["failed"] += 1
            continue

        try:
            is_update = str(path) in db_rows
            _upsert_track(conn, tags, art_dir, mtime)
            stats["updated" if is_update else "added"] += 1
        except Exception as exc:
            print(f"  [err]  {path.name}: {exc}")
            stats["failed"] += 1

        if (i + 1) % BATCH_SIZE == 0 or (i + 1) == total:
            conn.commit()
            print(f"  [{i+1}/{total}] committed")

    conn.commit()

    # ── 5. catch up on files scanned before musi read their quality ──────────
    _fill_quality(conn, progress)
    # ── 6. one-time: sharper covers for albums made at the old 160 px ────────
    _upgrade_art(conn, art_dir, progress)
    return stats


def _fill_quality(conn: sqlite3.Connection, progress=None) -> int:
    """Format details for local tracks that don't have them yet. Each file
    is probed once: a file mutagen can't read still gets a codec from its
    extension, so it isn't probed again on every start."""
    rows = conn.execute(
        "SELECT path FROM tracks WHERE codec IS NULL AND path NOT LIKE 'http%'").fetchall()
    for i, row in enumerate(rows):
        path = Path(row["path"])
        if progress:
            progress(i + 1, len(rows), path.name)
        q = quality.probe(path) or {"codec": path.suffix.lstrip(".").upper() or "?"}
        conn.execute(
            "UPDATE tracks SET codec = ?, bitrate = ?, sample_rate = ?, bit_depth = ?,"
            " channels = ? WHERE path = ?",
            (*(q.get(k) for k in quality.FIELDS), row["path"]))
        if (i + 1) % BATCH_SIZE == 0:
            conn.commit()
    conn.commit()
    return len(rows)


def _upgrade_art(conn: sqlite3.Connection, art_dir: Path, progress=None) -> int:
    """Re-render old 160 px album covers at the current size from the albums'
    own files — once (a marker file), and never over a cover someone picked
    (art.upgrade_thumb checks the old thumb was made from that same art)."""
    marker = art_dir / f".thumbs-{art.THUMB_SIZE[0]}"
    if marker.exists() or not art_dir.exists():
        return 0
    rows = conn.execute(
        """SELECT ar.name AS artist, al.title, MIN(t.path) AS path
           FROM albums al JOIN artists ar ON ar.id = al.artist_id
           JOIN tracks t ON t.album_id = al.id
           WHERE t.path NOT LIKE 'http%'
           GROUP BY al.id""").fetchall()
    done = 0
    for i, row in enumerate(rows):
        if progress:
            progress(i + 1, len(rows), row["title"])
        try:
            if art.upgrade_thumb(Path(row["path"]), art_dir,
                                 f"{row['artist']}::{row['title']}"):
                done += 1
        except Exception as exc:
            print(f"  [art] {row['title']}: {exc}")
    marker.touch()
    return done


# ── database helpers ──────────────────────────────────────────────────────────

def _upsert_track(
    conn: sqlite3.Connection,
    tags: TrackTags,
    art_dir: Path,
    mtime: float,
) -> None:
    artist_id = _get_or_create_artist(conn, tags.album_artist)
    album_id  = _get_or_create_album(conn, artist_id, tags, art_dir)

    q = tags.quality or {}
    conn.execute(
        """
        INSERT INTO tracks
            (album_id, artist_id, path, title, track_number, disc_number, duration, file_mtime,
             codec, bitrate, sample_rate, bit_depth, channels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            album_id     = excluded.album_id,
            artist_id    = excluded.artist_id,
            title        = excluded.title,
            track_number = excluded.track_number,
            disc_number  = excluded.disc_number,
            duration     = excluded.duration,
            file_mtime   = excluded.file_mtime,
            codec        = excluded.codec,
            bitrate      = excluded.bitrate,
            sample_rate  = excluded.sample_rate,
            bit_depth    = excluded.bit_depth,
            channels     = excluded.channels
        """,
        (
            album_id, artist_id, str(tags.path),
            tags.title, tags.track_number, tags.disc_number,
            tags.duration, mtime,
            *(q.get(k) for k in quality.FIELDS),
        ),
    )


def _get_or_create_artist(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM artists WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO artists (name) VALUES (?)", (name,)).lastrowid


def _get_or_create_album(
    conn: sqlite3.Connection,
    artist_id: int,
    tags: TrackTags,
    art_dir: Path,
) -> int:
    row = conn.execute(
        "SELECT id FROM albums WHERE artist_id = ? AND title = ?",
        (artist_id, tags.album),
    ).fetchone()
    if row:
        return row[0]

    album_key = f"{tags.album_artist}::{tags.album}"
    thumb, backdrop, palette = process_art(tags.path, art_dir, album_key)

    return conn.execute(
        """
        INSERT INTO albums (artist_id, title, year, art_path, backdrop_path, palette)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            artist_id, tags.album, tags.year,
            str(thumb)    if thumb    else None,
            str(backdrop) if backdrop else None,
            json.dumps(palette),
        ),
    ).lastrowid


def _remove_track(conn: sqlite3.Connection, path_str: str) -> None:
    conn.execute("DELETE FROM tracks WHERE path = ?", (path_str,))
    conn.execute(
        "DELETE FROM albums WHERE id NOT IN (SELECT DISTINCT album_id FROM tracks)"
    )
    conn.execute(
        "DELETE FROM artists WHERE id NOT IN (SELECT DISTINCT artist_id FROM tracks)"
    )
