"""Database connection and migration management."""

import sqlite3
from pathlib import Path

MIGRATIONS = [
    "001_initial.sql",
    "002_fts.sql",
]


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply any pending SQL migrations in order."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         INTEGER PRIMARY KEY,
            filename   TEXT NOT NULL UNIQUE,
            applied_at INTEGER NOT NULL DEFAULT (unixepoch())
        )
    """)
    conn.commit()

    migrations_dir = Path(__file__).parent / "migrations"

    for filename in MIGRATIONS:
        already = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = ?", (filename,)
        ).fetchone()
        if already:
            continue

        sql = (migrations_dir / filename).read_text()
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (filename,)
        )
        conn.commit()
        print(f"  [ok] migration applied: {filename}")
