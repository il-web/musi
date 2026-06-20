"""musi-library CLI.

Usage:
    musi-library scan              Full scan of MUSI_MUSIC_ROOT
    musi-library scan --force      Re-process every file regardless of mtime
    musi-library search <query>    FTS search across title / album / artist
    musi-library list              Print all artists -> albums -> tracks
    musi-library stats             Database summary
"""

import sys
from pathlib import Path

from musi.library.config import art_dir, db_path, music_root
from musi.library.db import open_db, run_migrations
from musi.library.scanner import scan


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return

    conn = open_db(db_path())
    run_migrations(conn)

    cmd = args[0]

    if cmd == "scan":
        force = "--force" in args
        stats = scan(music_root(), art_dir(), conn, force=force)
        print(f"\nScan complete: {stats['added']} added | "
              f"{stats['updated']} updated | {stats['skipped']} skipped | "
              f"{stats['failed']} failed | {stats['removed']} removed")

    elif cmd == "search":
        if len(args) < 2:
            print("Usage: musi-library search <query>")
            sys.exit(1)
        query = " ".join(args[1:])
        rows = conn.execute(
            """
            SELECT t.title, al.title, ar.name, t.duration
            FROM tracks_fts f
            JOIN tracks  t  ON t.id  = f.rowid
            JOIN albums  al ON al.id = t.album_id
            JOIN artists ar ON ar.id = t.artist_id
            WHERE tracks_fts MATCH ?
            LIMIT 20
            """,
            (f"{query}*",),
        ).fetchall()
        if not rows:
            print(f"No results for '{query}'")
        for r in rows:
            mins, secs = divmod(int(r["duration"]), 60)
            print(f"  {r[0]:<40} {r[1]:<30} {r[2]:<25} {mins}:{secs:02d}")

    elif cmd == "list":
        artists = conn.execute("SELECT id, name FROM artists ORDER BY name").fetchall()
        for artist in artists:
            print(f"\n{artist['name']}")
            albums = conn.execute(
                "SELECT id, title, year FROM albums WHERE artist_id = ? ORDER BY year, title",
                (artist["id"],),
            ).fetchall()
            for album in albums:
                tracks = conn.execute(
                    "SELECT title, track_number, duration FROM tracks "
                    "WHERE album_id = ? ORDER BY disc_number, track_number",
                    (album["id"],),
                ).fetchall()
                year = f" ({album['year']})" if album["year"] else ""
                print(f"  {album['title']}{year} — {len(tracks)} tracks")
                for t in tracks:
                    mins, secs = divmod(int(t["duration"]), 60)
                    num = f"{t['track_number']:02d}." if t["track_number"] else "  "
                    print(f"    {num} {t['title']:<45} {mins}:{secs:02d}")

    elif cmd == "stats":
        artists = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
        albums  = conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
        tracks  = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        dur     = conn.execute("SELECT SUM(duration) FROM tracks").fetchone()[0] or 0
        hours, rem = divmod(int(dur), 3600)
        mins = rem // 60
        print(f"Artists : {artists}")
        print(f"Albums  : {albums}")
        print(f"Tracks  : {tracks}")
        print(f"Duration: {hours}h {mins}m")
        print(f"Database: {db_path()}")
        print(f"Music   : {music_root()}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
