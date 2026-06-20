# musi 02 — Library Indexer & SQLite Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `musi-library`, the service that scans `/music`, reads tags, extracts album art, pre-renders display assets, and maintains a SQLite database for the UI to query. By the end of this plan you can point `musi-library` at a folder of music files on your Linux dev PC and get a fully populated DB plus a directory of rendered art assets, queryable via a small CLI.

**Architecture:** Pure-Python module under `src/musi/library/`. SQLite with WAL mode for concurrency. FTS5 virtual table for fuzzy search. Migration system so the schema can evolve without manual DB surgery. Art pipeline runs at scan time (never at runtime). Inotify-based watcher for live filesystem changes. CLI wrapper for manual scan + inspection during development.

**Tech Stack:** Python 3.11+, SQLite 3 (with FTS5), `mutagen` for tag reading, `Pillow` for image work, `watchdog` for cross-platform inotify, `pytest` for tests. All works on Debian 12 / Ubuntu 24.04 dev PC; identical packages on Pi OS Lite.

**Prerequisites:**
- Plan 01 completed up to Task 1 (project skeleton exists). The Pi hardware is **NOT required** for this plan — everything runs on your Linux dev PC.
- Debian 12 (Bookworm) or compatible Linux distro on your dev PC
- Python 3.11+
- A small directory of test music files you own (we'll generate synthetic fixtures too, but having real files is useful for ad-hoc verification)

**Configuration model:** the library service reads three env vars. Defaults shown:

| Env var | Default | Meaning |
|---|---|---|
| `MUSI_MUSIC_ROOT` | `/music` (prod) or `~/music` (dev fallback) | Where to scan |
| `MUSI_DB_PATH` | `/var/lib/musi/library.db` (prod) or `~/.local/share/musi/library.db` (dev) | SQLite database path |
| `MUSI_ART_DIR` | `/var/lib/musi/art` (prod) or `~/.local/share/musi/art` (dev) | Pre-rendered art output dir |

The dev defaults are XDG-compliant and won't conflict with prod paths if you ever copy code to a Pi.

---

## File Structure

Files this plan creates:

```
musi/
├── src/musi/
│   ├── library/
│   │   ├── __init__.py
│   │   ├── config.py                # Env var loading, path resolution
│   │   ├── db.py                    # Connection management, migrations
│   │   ├── models.py                # Dataclasses for Track/Artist/Album
│   │   ├── tags.py                  # Mutagen-based tag reading
│   │   ├── scanner.py               # File walker, incremental logic
│   │   ├── art.py                   # Art extraction, resize, blur, palette
│   │   ├── service.py               # Long-running service entry point
│   │   ├── cli.py                   # `musi-library` CLI
│   │   └── migrations/
│   │       ├── __init__.py
│   │       ├── 001_initial.sql
│   │       └── 002_fts.sql
│   └── __main__.py                  # Updated to add `library` subcommands
├── tests/
│   ├── test_library_config.py
│   ├── test_library_db.py
│   ├── test_library_models.py
│   ├── test_library_tags.py
│   ├── test_library_scanner.py
│   ├── test_library_art.py
│   ├── test_library_service.py
│   ├── test_library_cli.py
│   ├── conftest.py                  # Shared fixtures (generated audio)
│   └── helpers/
│       ├── __init__.py
│       └── audio_fixtures.py        # Generate small synthetic audio files
└── docs/
    └── LIBRARY.md
```

---

## Task 1: Dev environment setup on Debian 12

**Files:** None (env setup only)

- [ ] **Step 1: Install OS packages**

```bash
sudo apt update
sudo apt install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    python3-pygame python3-evdev python3-mpd2 \
    python3-pil python3-mutagen python3-watchdog \
    ffmpeg \
    mpd mpc alsa-utils \
    git rsync \
    sqlite3
```

Why each:
- `ffmpeg` is needed by the audio-fixture generator to make synthetic test files
- `sqlite3` CLI for inspecting the database during development
- The Python packages are the same set you'll use on the Pi

- [ ] **Step 2: Verify versions**

```bash
python3 --version           # expect: 3.11.x or higher
sqlite3 --version           # expect: 3.40+ (Bookworm ships 3.40.1)
python3 -c "import sqlite3; print('FTS5:', 'fts5' in sqlite3.connect(':memory:').execute('select sqlite_compile_options()').fetchone()[0].lower() or 'enabled by default')"
```

The FTS5 check is important — SQLite must be built with FTS5 support. Debian's stock SQLite has it. If your distro doesn't, the rest of this plan won't work.

- [ ] **Step 3: Confirm git checkout from Plan 01 exists**

```bash
cd ~/path/to/musi   # wherever you cloned/synced the project
git status
git log --oneline -5
```

Expected: clean working tree with Plan 01 commits visible. If you don't have the project on your Linux PC yet, transfer it from your Windows dev box (e.g., `rsync` it across, or push to a git remote and clone).

- [ ] **Step 4: Create a Python venv for the project**

```bash
cd ~/path/to/musi
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

The `-e ".[dev]"` installs musi as an editable package plus its dev dependencies (pytest, pytest-mock). The system-wide apt packages above will satisfy runtime deps; the venv gives you a clean pytest environment.

- [ ] **Step 5: Run existing tests to make sure the venv works**

```bash
python -m pytest -v
```

Expected: the Plan 01 tests (`test_inputs.py`, `test_hello.py`) pass. If `test_hello.py` complains about pygame, install pygame in the venv too: `pip install pygame`.

---

## Task 2: Library package skeleton + config module

**Files:**
- Create: `src/musi/library/__init__.py`
- Create: `src/musi/library/config.py`
- Create: `tests/test_library_config.py`

- [ ] **Step 1: Write failing test for config loading**

`tests/test_library_config.py`:

```python
"""Tests for library config (env var resolution, defaults)."""
from __future__ import annotations

from pathlib import Path

import pytest

from musi.library.config import LibraryConfig


def test_config_defaults_to_xdg_paths_in_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSI_MUSIC_ROOT", raising=False)
    monkeypatch.delenv("MUSI_DB_PATH", raising=False)
    monkeypatch.delenv("MUSI_ART_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))

    cfg = LibraryConfig.from_env()

    assert cfg.music_root == Path.home() / "music"
    assert cfg.db_path == tmp_path / ".local" / "share" / "musi" / "library.db"
    assert cfg.art_dir == tmp_path / ".local" / "share" / "musi" / "art"


def test_config_honors_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSI_MUSIC_ROOT", str(tmp_path / "mymusic"))
    monkeypatch.setenv("MUSI_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("MUSI_ART_DIR", str(tmp_path / "art"))

    cfg = LibraryConfig.from_env()

    assert cfg.music_root == tmp_path / "mymusic"
    assert cfg.db_path == tmp_path / "db.sqlite"
    assert cfg.art_dir == tmp_path / "art"


def test_config_ensure_dirs_creates_parents(monkeypatch, tmp_path):
    db_path = tmp_path / "deep" / "nested" / "library.db"
    art_dir = tmp_path / "deep" / "art"
    monkeypatch.setenv("MUSI_DB_PATH", str(db_path))
    monkeypatch.setenv("MUSI_ART_DIR", str(art_dir))
    monkeypatch.setenv("MUSI_MUSIC_ROOT", str(tmp_path / "music"))

    cfg = LibraryConfig.from_env()
    cfg.ensure_dirs()

    assert db_path.parent.is_dir()
    assert art_dir.is_dir()
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'musi.library'`

- [ ] **Step 3: Implement config module**

`src/musi/library/__init__.py`:

```python
"""musi-library: file scanner, tag indexer, art pipeline, SQLite store."""
```

`src/musi/library/config.py`:

```python
"""Configuration for the library service.

Resolution order for each setting:
1. Explicit env var (MUSI_MUSIC_ROOT, MUSI_DB_PATH, MUSI_ART_DIR)
2. XDG-compliant dev default under $HOME/.local/share/musi
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _xdg_data_home() -> Path:
    if env := os.environ.get("XDG_DATA_HOME"):
        return Path(env)
    return Path.home() / ".local" / "share"


@dataclass(frozen=True)
class LibraryConfig:
    music_root: Path
    db_path: Path
    art_dir: Path

    @classmethod
    def from_env(cls) -> "LibraryConfig":
        data_home = _xdg_data_home() / "musi"
        music_root = Path(os.environ.get("MUSI_MUSIC_ROOT") or Path.home() / "music")
        db_path = Path(os.environ.get("MUSI_DB_PATH") or data_home / "library.db")
        art_dir = Path(os.environ.get("MUSI_ART_DIR") or data_home / "art")
        return cls(music_root=music_root, db_path=db_path, art_dir=art_dir)

    def ensure_dirs(self) -> None:
        """Create parent directories for db + art dir if missing."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.art_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run, verify pass**

```bash
python -m pytest tests/test_library_config.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/__init__.py src/musi/library/config.py tests/test_library_config.py
git commit -m "feat(library): config module with env var + XDG defaults"
```

---

## Task 3: SQLite schema — initial migration

**Files:**
- Create: `src/musi/library/migrations/__init__.py`
- Create: `src/musi/library/migrations/001_initial.sql`
- Create: `src/musi/library/db.py`
- Create: `tests/test_library_db.py`

- [ ] **Step 1: Write the migration SQL**

`src/musi/library/migrations/001_initial.sql`:

```sql
-- Initial schema. Created by 001_initial.sql.

CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE artists (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    sort_name   TEXT NOT NULL,
    UNIQUE (name)
);

CREATE INDEX idx_artists_sort_name ON artists (sort_name);

CREATE TABLE albums (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    artist_id       INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    year            INTEGER,
    art_path        TEXT,
    backdrop_path   TEXT,
    color_primary   TEXT,   -- hex like "#7F4A2B"
    color_accent    TEXT,
    color_text      TEXT,
    UNIQUE (artist_id, title)
);

CREATE INDEX idx_albums_artist ON albums (artist_id);
CREATE INDEX idx_albums_title  ON albums (title);

CREATE TABLE tracks (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    artist_id       INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    album_id        INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    track_no        INTEGER,
    disc_no         INTEGER,
    duration_ms     INTEGER,
    year            INTEGER,
    genre           TEXT,
    bitrate         INTEGER,
    format          TEXT,
    mtime           INTEGER NOT NULL,
    added_at        INTEGER NOT NULL  -- unix epoch seconds
);

CREATE INDEX idx_tracks_album      ON tracks (album_id, disc_no, track_no);
CREATE INDEX idx_tracks_artist     ON tracks (artist_id);
CREATE INDEX idx_tracks_added_at   ON tracks (added_at DESC);
CREATE INDEX idx_tracks_mtime      ON tracks (mtime);

CREATE TABLE play_history (
    id          INTEGER PRIMARY KEY,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    played_at   INTEGER NOT NULL
);

CREATE INDEX idx_play_history_track     ON play_history (track_id);
CREATE INDEX idx_play_history_played_at ON play_history (played_at DESC);

CREATE TABLE settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

INSERT INTO schema_version (version) VALUES (1);
```

`src/musi/library/migrations/__init__.py`:

```python
"""SQL migration files for the library DB.

Each file is named NNN_description.sql and is applied in numerical order.
A migration is applied iff schema_version.version < its number.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

_FILENAME_RE = re.compile(r"^(\d{3})_.+\.sql$")


def discover() -> List[Tuple[int, Path]]:
    """Return [(version, path), ...] sorted ascending by version."""
    here = Path(__file__).parent
    out: List[Tuple[int, Path]] = []
    for f in here.iterdir():
        if not f.is_file():
            continue
        m = _FILENAME_RE.match(f.name)
        if not m:
            continue
        out.append((int(m.group(1)), f))
    out.sort(key=lambda pair: pair[0])
    return out
```

- [ ] **Step 2: Write failing test for the DB module**

`tests/test_library_db.py`:

```python
"""Tests for SQLite connection management + migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from musi.library.db import Database, open_database
from musi.library.config import LibraryConfig


@pytest.fixture
def temp_config(tmp_path) -> LibraryConfig:
    return LibraryConfig(
        music_root=tmp_path / "music",
        db_path=tmp_path / "library.db",
        art_dir=tmp_path / "art",
    )


def test_open_database_creates_file(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    db.close()
    assert temp_config.db_path.is_file()


def test_open_database_applies_initial_migration(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    version = db.connection.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version >= 1


def test_open_database_creates_expected_tables(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    rows = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert {"artists", "albums", "tracks", "play_history", "settings", "schema_version"} <= names


def test_open_database_is_idempotent(temp_config):
    temp_config.ensure_dirs()
    db1 = open_database(temp_config)
    db1.close()
    db2 = open_database(temp_config)
    version = db2.connection.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version >= 1
    db2.close()


def test_database_uses_wal_mode(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    mode = db.connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_database_enables_foreign_keys(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    enabled = db.connection.execute("PRAGMA foreign_keys").fetchone()[0]
    assert enabled == 1
```

- [ ] **Step 3: Run, verify failure**

```bash
python -m pytest tests/test_library_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'musi.library.db'`.

- [ ] **Step 4: Implement the DB module**

`src/musi/library/db.py`:

```python
"""SQLite connection management + migration runner.

Opens the database, applies any pending migrations, sets WAL mode and
foreign keys, returns a Database wrapper. Read-only handles for the UI
will use the same file but in `mode=ro` URI form.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from musi.library.config import LibraryConfig
from musi.library.migrations import discover as discover_migrations


@dataclass
class Database:
    connection: sqlite3.Connection

    def close(self) -> None:
        self.connection.close()


def open_database(config: LibraryConfig) -> Database:
    """Open (or create) the library DB and bring its schema up to date."""
    config.ensure_dirs()
    conn = sqlite3.connect(
        config.db_path,
        isolation_level=None,  # autocommit; we use explicit transactions
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")  # WAL safe at NORMAL
    conn.execute("PRAGMA temp_store = MEMORY")

    _ensure_schema_version_table(conn)
    _apply_pending_migrations(conn)

    return Database(connection=conn)


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )


def _current_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return (row[0] or 0) if row else 0


def _apply_pending_migrations(conn: sqlite3.Connection) -> None:
    current = _current_schema_version(conn)
    for version, path in discover_migrations():
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.execute("BEGIN")
        try:
            conn.executescript(sql)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
```

- [ ] **Step 5: Run tests, verify pass**

```bash
python -m pytest tests/test_library_db.py -v
```

Expected: 6 PASS.

- [ ] **Step 6: Sanity-check the schema with sqlite3 CLI**

```bash
python -c "from musi.library.config import LibraryConfig; from musi.library.db import open_database; cfg = LibraryConfig.from_env(); db = open_database(cfg); db.close(); print('DB at', cfg.db_path)"
sqlite3 ~/.local/share/musi/library.db ".schema"
```

Expected: full schema dump showing all six tables.

- [ ] **Step 7: Commit**

```bash
git add src/musi/library/db.py src/musi/library/migrations/ tests/test_library_db.py
git commit -m "feat(library): SQLite schema + migration runner"
```

---

## Task 4: FTS5 search migration (migration 002)

**Files:**
- Create: `src/musi/library/migrations/002_fts.sql`

- [ ] **Step 1: Write failing test**

Append to `tests/test_library_db.py`:

```python
def test_fts5_tracks_search_table_exists(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    rows = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE name='tracks_fts'"
    ).fetchall()
    assert len(rows) == 1


def test_fts5_inserts_propagate_via_trigger(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    c = db.connection
    c.execute("INSERT INTO artists(name, sort_name) VALUES (?, ?)", ("Radiohead", "radiohead"))
    artist_id = c.execute("SELECT id FROM artists WHERE name=?", ("Radiohead",)).fetchone()[0]
    c.execute(
        "INSERT INTO albums(title, artist_id) VALUES (?, ?)",
        ("OK Computer", artist_id),
    )
    album_id = c.execute("SELECT id FROM albums WHERE title=?", ("OK Computer",)).fetchone()[0]
    c.execute(
        "INSERT INTO tracks(path, title, artist_id, album_id, mtime, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("/m/karma.flac", "Karma Police", artist_id, album_id, 0, 0),
    )

    # FTS rebuilds itself via INSERT/UPDATE/DELETE triggers
    results = c.execute(
        "SELECT title FROM tracks_fts WHERE tracks_fts MATCH 'karma'"
    ).fetchall()
    assert [r[0] for r in results] == ["Karma Police"]


def test_fts5_search_matches_artist_or_album_or_title(temp_config):
    temp_config.ensure_dirs()
    db = open_database(temp_config)
    c = db.connection
    c.execute("INSERT INTO artists(name, sort_name) VALUES (?, ?)", ("Radiohead", "radiohead"))
    aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO albums(title, artist_id) VALUES (?, ?)", ("OK Computer", aid))
    abid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute(
        "INSERT INTO tracks(path, title, artist_id, album_id, mtime, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("/m/karma.flac", "Karma Police", aid, abid, 0, 0),
    )

    by_artist = c.execute("SELECT title FROM tracks_fts WHERE tracks_fts MATCH 'radiohead'").fetchall()
    by_album = c.execute("SELECT title FROM tracks_fts WHERE tracks_fts MATCH 'computer'").fetchall()
    by_title = c.execute("SELECT title FROM tracks_fts WHERE tracks_fts MATCH 'police'").fetchall()

    assert by_artist == [("Karma Police",)]
    assert by_album == [("Karma Police",)]
    assert by_title == [("Karma Police",)]
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_db.py::test_fts5_tracks_search_table_exists -v
```

Expected: FAIL (table doesn't exist yet).

- [ ] **Step 3: Write the FTS migration**

`src/musi/library/migrations/002_fts.sql`:

```sql
-- FTS5 search across tracks. Indexed columns are denormalized into the
-- virtual table; triggers keep it in sync with tracks/artists/albums.

-- Regular FTS5 (content is stored in the index). Slight duplication with
-- tracks/artists/albums, but tests + simple queries can read columns back.
CREATE VIRTUAL TABLE tracks_fts USING fts5 (
    title,
    artist_name,
    album_title
);

-- Insert into FTS on track insert. Pull artist + album names via joins.
CREATE TRIGGER tracks_fts_after_insert
AFTER INSERT ON tracks
BEGIN
    INSERT INTO tracks_fts(rowid, title, artist_name, album_title)
    SELECT NEW.id, NEW.title, ar.name, al.title
    FROM artists ar, albums al
    WHERE ar.id = NEW.artist_id AND al.id = NEW.album_id;
END;

CREATE TRIGGER tracks_fts_after_update
AFTER UPDATE ON tracks
BEGIN
    DELETE FROM tracks_fts WHERE rowid = OLD.id;
    INSERT INTO tracks_fts(rowid, title, artist_name, album_title)
    SELECT NEW.id, NEW.title, ar.name, al.title
    FROM artists ar, albums al
    WHERE ar.id = NEW.artist_id AND al.id = NEW.album_id;
END;

CREATE TRIGGER tracks_fts_after_delete
AFTER DELETE ON tracks
BEGIN
    DELETE FROM tracks_fts WHERE rowid = OLD.id;
END;

-- When an artist's name changes, refresh all their tracks' FTS rows.
CREATE TRIGGER tracks_fts_after_artist_update
AFTER UPDATE OF name ON artists
BEGIN
    DELETE FROM tracks_fts WHERE rowid IN (SELECT id FROM tracks WHERE artist_id = NEW.id);
    INSERT INTO tracks_fts(rowid, title, artist_name, album_title)
    SELECT t.id, t.title, NEW.name, al.title
    FROM tracks t JOIN albums al ON al.id = t.album_id
    WHERE t.artist_id = NEW.id;
END;

-- When an album's title changes, refresh all its tracks' FTS rows.
CREATE TRIGGER tracks_fts_after_album_update
AFTER UPDATE OF title ON albums
BEGIN
    DELETE FROM tracks_fts WHERE rowid IN (SELECT id FROM tracks WHERE album_id = NEW.id);
    INSERT INTO tracks_fts(rowid, title, artist_name, album_title)
    SELECT t.id, t.title, ar.name, NEW.title
    FROM tracks t JOIN artists ar ON ar.id = t.artist_id
    WHERE t.album_id = NEW.id;
END;

INSERT INTO schema_version(version) VALUES (2);
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python -m pytest tests/test_library_db.py -v
```

Expected: 9 PASS (6 prior + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/migrations/002_fts.sql tests/test_library_db.py
git commit -m "feat(library): FTS5 search with sync triggers"
```

---

## Task 5: Dataclass models

**Files:**
- Create: `src/musi/library/models.py`
- Create: `tests/test_library_models.py`

- [ ] **Step 1: Write failing test**

`tests/test_library_models.py`:

```python
"""Tests for library dataclass models."""
from __future__ import annotations

from musi.library.models import Artist, Album, Track


def test_artist_sort_name_defaults_to_lowercased_name():
    a = Artist.from_name("Radiohead")
    assert a.name == "Radiohead"
    assert a.sort_name == "radiohead"


def test_artist_sort_name_strips_leading_the():
    a = Artist.from_name("The Beatles")
    assert a.sort_name == "beatles"


def test_artist_sort_name_strips_leading_a():
    a = Artist.from_name("A Tribe Called Quest")
    assert a.sort_name == "tribe called quest"


def test_artist_sort_name_strips_leading_an():
    a = Artist.from_name("An Album By Someone")
    assert a.sort_name == "album by someone"


def test_artist_sort_name_unicode_normalize():
    a = Artist.from_name("Björk")
    # Sort name should fold to ASCII for sorting purposes
    assert a.sort_name == "bjork"


def test_album_dataclass_fields():
    a = Album(
        id=1, title="OK Computer", artist_id=1, year=1997,
        art_path=None, backdrop_path=None,
        color_primary=None, color_accent=None, color_text=None,
    )
    assert a.title == "OK Computer"
    assert a.year == 1997


def test_track_dataclass_fields():
    t = Track(
        id=1, path="/m/karma.flac", title="Karma Police",
        artist_id=1, album_id=1, track_no=6, disc_no=1,
        duration_ms=263000, year=1997, genre="Alternative",
        bitrate=1024, format="flac", mtime=1700000000, added_at=1700000000,
    )
    assert t.duration_ms == 263000
    assert t.format == "flac"
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_models.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement models**

`src/musi/library/models.py`:

```python
"""Dataclass models for library entities.

These mirror the SQLite schema. Construction is intentionally cheap — no
DB access. Population happens via row factories in the scanner.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_LEADING_ARTICLE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def _ascii_fold(s: str) -> str:
    """Fold unicode characters to closest ASCII for sort purposes."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def make_sort_name(name: str) -> str:
    """Produce a stable, lowercase, article-stripped, ASCII-folded sort key."""
    folded = _ascii_fold(name).lower().strip()
    folded = _LEADING_ARTICLE.sub("", folded)
    return folded


@dataclass(frozen=True)
class Artist:
    id: Optional[int]
    name: str
    sort_name: str

    @classmethod
    def from_name(cls, name: str) -> "Artist":
        return cls(id=None, name=name, sort_name=make_sort_name(name))


@dataclass(frozen=True)
class Album:
    id: Optional[int]
    title: str
    artist_id: int
    year: Optional[int]
    art_path: Optional[str]
    backdrop_path: Optional[str]
    color_primary: Optional[str]
    color_accent: Optional[str]
    color_text: Optional[str]


@dataclass(frozen=True)
class Track:
    id: Optional[int]
    path: str
    title: str
    artist_id: int
    album_id: int
    track_no: Optional[int]
    disc_no: Optional[int]
    duration_ms: Optional[int]
    year: Optional[int]
    genre: Optional[str]
    bitrate: Optional[int]
    format: Optional[str]
    mtime: int
    added_at: int
```

- [ ] **Step 4: Run, verify pass**

```bash
python -m pytest tests/test_library_models.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/models.py tests/test_library_models.py
git commit -m "feat(library): dataclass models with sort-name helper"
```

---

## Task 6: Audio fixture generator (test helper)

**Files:**
- Create: `tests/helpers/__init__.py`
- Create: `tests/helpers/audio_fixtures.py`
- Create: `tests/conftest.py`

This generates small synthetic audio files at test-collection time so we don't ship binary blobs in the repo.

- [ ] **Step 1: Write the audio fixture generator**

`tests/helpers/__init__.py`: (empty)

`tests/helpers/audio_fixtures.py`:

```python
"""Generate small synthetic audio files for tests.

Uses ffmpeg to create 1-second sine-wave MP3/FLAC files, then mutagen to
write controlled metadata tags. Cached in a per-session tmp dir.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class FakeTrackSpec:
    relative_path: str
    title: str
    artist: str
    album: str
    track_no: int
    year: int = 2020
    genre: str = "Electronic"
    duration_s: float = 1.0
    fmt: str = "mp3"  # 'mp3' or 'flac'


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        import pytest
        pytest.skip("ffmpeg not installed; skipping audio fixture tests")


def make_track(target_dir: Path, spec: FakeTrackSpec) -> Path:
    """Create one synthetic audio file at target_dir/spec.relative_path."""
    require_ffmpeg()
    out = target_dir / spec.relative_path
    out.parent.mkdir(parents=True, exist_ok=True)

    if spec.fmt == "mp3":
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={spec.duration_s}",
                "-ac", "2", "-ar", "44100", "-b:a", "128k",
                str(out),
            ],
            check=True,
        )
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError
        try:
            tags = EasyID3(out)
        except ID3NoHeaderError:
            from mutagen.mp3 import MP3
            mp3 = MP3(out)
            mp3.add_tags()
            mp3.save()
            tags = EasyID3(out)
        tags["title"] = spec.title
        tags["artist"] = spec.artist
        tags["album"] = spec.album
        tags["tracknumber"] = str(spec.track_no)
        tags["date"] = str(spec.year)
        tags["genre"] = spec.genre
        tags.save()
    elif spec.fmt == "flac":
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={spec.duration_s}",
                "-ac", "2", "-ar", "44100",
                str(out),
            ],
            check=True,
        )
        from mutagen.flac import FLAC
        flac = FLAC(out)
        flac["title"] = spec.title
        flac["artist"] = spec.artist
        flac["album"] = spec.album
        flac["tracknumber"] = str(spec.track_no)
        flac["date"] = str(spec.year)
        flac["genre"] = spec.genre
        flac.save()
    else:
        raise ValueError(f"unsupported format {spec.fmt!r}")

    return out


def make_corpus(target_dir: Path, specs: List[FakeTrackSpec]) -> List[Path]:
    return [make_track(target_dir, s) for s in specs]


def default_specs() -> List[FakeTrackSpec]:
    """A small but interesting corpus exercising multiple artists/albums/years/formats."""
    return [
        FakeTrackSpec(relative_path="Radiohead/OK Computer/01 Airbag.mp3",
                     title="Airbag", artist="Radiohead", album="OK Computer", track_no=1, year=1997),
        FakeTrackSpec(relative_path="Radiohead/OK Computer/06 Karma Police.mp3",
                     title="Karma Police", artist="Radiohead", album="OK Computer", track_no=6, year=1997),
        FakeTrackSpec(relative_path="The Beatles/Abbey Road/01 Come Together.flac",
                     title="Come Together", artist="The Beatles", album="Abbey Road", track_no=1, year=1969, fmt="flac"),
        FakeTrackSpec(relative_path="Björk/Homogenic/02 Joga.flac",
                     title="Jóga", artist="Björk", album="Homogenic", track_no=2, year=1997, fmt="flac"),
    ]
```

- [ ] **Step 2: Write conftest**

`tests/conftest.py`:

```python
"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.audio_fixtures import default_specs, make_corpus


@pytest.fixture(scope="session")
def synthetic_corpus(tmp_path_factory) -> Path:
    """A directory of synthetic audio files. Built once per session."""
    root = tmp_path_factory.mktemp("musi-music")
    make_corpus(root, default_specs())
    return root
```

- [ ] **Step 3: Sanity check — fixtures generate without error**

```bash
python -m pytest --collect-only -q
```

Expected: collection succeeds. (No tests exercise these fixtures yet.)

Also try generating them manually:

```bash
python -c "
from pathlib import Path
import tempfile
from tests.helpers.audio_fixtures import default_specs, make_corpus
d = Path(tempfile.mkdtemp())
paths = make_corpus(d, default_specs())
for p in paths:
    print(p.relative_to(d), p.stat().st_size, 'bytes')
"
```

Expected: 4 files printed with non-zero sizes.

- [ ] **Step 4: Commit**

```bash
git add tests/helpers/ tests/conftest.py
git commit -m "test: synthetic audio corpus generator (ffmpeg + mutagen)"
```

---

## Task 7: Tag reader (mutagen wrapper)

**Files:**
- Create: `src/musi/library/tags.py`
- Create: `tests/test_library_tags.py`

- [ ] **Step 1: Write failing test**

`tests/test_library_tags.py`:

```python
"""Tests for tag reading via mutagen."""
from __future__ import annotations

from pathlib import Path

import pytest

from musi.library.tags import read_tags, TagReadError


def test_read_tags_mp3(synthetic_corpus: Path):
    f = synthetic_corpus / "Radiohead" / "OK Computer" / "06 Karma Police.mp3"
    info = read_tags(f)
    assert info.title == "Karma Police"
    assert info.artist == "Radiohead"
    assert info.album == "OK Computer"
    assert info.track_no == 6
    assert info.year == 1997
    assert info.genre == "Electronic"
    assert info.format == "mp3"
    assert info.duration_ms is not None and info.duration_ms >= 1000
    assert info.bitrate is not None and info.bitrate > 0


def test_read_tags_flac(synthetic_corpus: Path):
    f = synthetic_corpus / "The Beatles" / "Abbey Road" / "01 Come Together.flac"
    info = read_tags(f)
    assert info.title == "Come Together"
    assert info.artist == "The Beatles"
    assert info.album == "Abbey Road"
    assert info.track_no == 1
    assert info.year == 1969
    assert info.format == "flac"


def test_read_tags_unicode(synthetic_corpus: Path):
    f = synthetic_corpus / "Björk" / "Homogenic" / "02 Joga.flac"
    info = read_tags(f)
    assert info.title == "Jóga"
    assert info.artist == "Björk"


def test_read_tags_raises_for_missing_file(tmp_path):
    with pytest.raises(TagReadError):
        read_tags(tmp_path / "nope.mp3")


def test_read_tags_raises_for_non_audio_file(tmp_path):
    f = tmp_path / "not-audio.txt"
    f.write_text("hello")
    with pytest.raises(TagReadError):
        read_tags(f)
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_tags.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement tag reader**

`src/musi/library/tags.py`:

```python
"""Read audio file tags via mutagen.

Returns a typed `TagInfo` with normalized fields. Tracks that fail to parse
raise `TagReadError` — the scanner catches this and logs/skips.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class TagReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class TagInfo:
    title: str
    artist: str
    album: str
    track_no: Optional[int]
    disc_no: Optional[int]
    year: Optional[int]
    genre: Optional[str]
    duration_ms: Optional[int]
    bitrate: Optional[int]
    format: str


def read_tags(path: Path) -> TagInfo:
    if not path.is_file():
        raise TagReadError(f"file not found: {path}")

    try:
        import mutagen
    except ImportError as e:  # pragma: no cover
        raise TagReadError("mutagen is not installed") from e

    try:
        f = mutagen.File(path, easy=True)
    except Exception as e:
        raise TagReadError(f"mutagen failed to open {path}: {e}") from e

    if f is None:
        raise TagReadError(f"not a recognized audio file: {path}")

    suffix = path.suffix.lower().lstrip(".")
    duration_ms = int(f.info.length * 1000) if getattr(f, "info", None) else None
    bitrate = getattr(f.info, "bitrate", None) if getattr(f, "info", None) else None

    def _first(key: str) -> Optional[str]:
        v = f.get(key)
        if not v:
            return None
        if isinstance(v, list):
            return v[0] if v else None
        return str(v)

    def _int(key: str) -> Optional[int]:
        s = _first(key)
        if not s:
            return None
        # Track numbers may be "6/12"; pick the first part.
        head = s.split("/", 1)[0].strip()
        try:
            return int(head)
        except ValueError:
            return None

    def _year() -> Optional[int]:
        for key in ("date", "year", "originaldate"):
            s = _first(key)
            if not s:
                continue
            try:
                return int(s[:4])
            except (ValueError, TypeError):
                continue
        return None

    title = _first("title") or path.stem
    artist = _first("artist") or "Unknown Artist"
    album = _first("album") or "Unknown Album"

    return TagInfo(
        title=title,
        artist=artist,
        album=album,
        track_no=_int("tracknumber"),
        disc_no=_int("discnumber"),
        year=_year(),
        genre=_first("genre"),
        duration_ms=duration_ms,
        bitrate=bitrate,
        format=suffix or "unknown",
    )
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python -m pytest tests/test_library_tags.py -v
```

Expected: 5 PASS (or skipped if ffmpeg is missing — install it).

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/tags.py tests/test_library_tags.py
git commit -m "feat(library): tag reader (mutagen wrapper)"
```

---

## Task 8: Upsert helpers for artist + album + track

**Files:**
- Create: `src/musi/library/scanner.py` (initial — just upsert helpers)
- Create: `tests/test_library_scanner.py`

- [ ] **Step 1: Write failing test**

`tests/test_library_scanner.py`:

```python
"""Tests for the library scanner: upserts, file walking, full scan, incremental."""
from __future__ import annotations

from pathlib import Path

import pytest

from musi.library.config import LibraryConfig
from musi.library.db import open_database
from musi.library.scanner import upsert_artist, upsert_album


@pytest.fixture
def db_handle(tmp_path):
    cfg = LibraryConfig(
        music_root=tmp_path / "music",
        db_path=tmp_path / "library.db",
        art_dir=tmp_path / "art",
    )
    db = open_database(cfg)
    yield db
    db.close()


def test_upsert_artist_returns_id(db_handle):
    aid = upsert_artist(db_handle.connection, "Radiohead")
    assert isinstance(aid, int)
    assert aid > 0


def test_upsert_artist_is_idempotent(db_handle):
    a1 = upsert_artist(db_handle.connection, "Radiohead")
    a2 = upsert_artist(db_handle.connection, "Radiohead")
    assert a1 == a2


def test_upsert_artist_stores_sort_name(db_handle):
    upsert_artist(db_handle.connection, "The Beatles")
    sort_name = db_handle.connection.execute(
        "SELECT sort_name FROM artists WHERE name = ?", ("The Beatles",)
    ).fetchone()[0]
    assert sort_name == "beatles"


def test_upsert_album_links_to_artist(db_handle):
    artist_id = upsert_artist(db_handle.connection, "Radiohead")
    album_id = upsert_album(db_handle.connection, artist_id, "OK Computer", year=1997)
    row = db_handle.connection.execute(
        "SELECT title, artist_id, year FROM albums WHERE id = ?", (album_id,)
    ).fetchone()
    assert row == ("OK Computer", artist_id, 1997)


def test_upsert_album_idempotent_per_artist(db_handle):
    artist_id = upsert_artist(db_handle.connection, "Radiohead")
    a1 = upsert_album(db_handle.connection, artist_id, "OK Computer", year=1997)
    a2 = upsert_album(db_handle.connection, artist_id, "OK Computer", year=1997)
    assert a1 == a2


def test_two_artists_can_have_same_album_title(db_handle):
    a1 = upsert_artist(db_handle.connection, "Artist One")
    a2 = upsert_artist(db_handle.connection, "Artist Two")
    alb1 = upsert_album(db_handle.connection, a1, "Greatest Hits", year=2000)
    alb2 = upsert_album(db_handle.connection, a2, "Greatest Hits", year=2010)
    assert alb1 != alb2
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_scanner.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement scanner upserts**

`src/musi/library/scanner.py`:

```python
"""Library scanner: walks the filesystem, upserts artists/albums/tracks.

This module is intentionally split across multiple functions so each
piece is testable in isolation. The top-level entry point is `full_scan`
(added in a later task).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from musi.library.models import make_sort_name


def upsert_artist(conn: sqlite3.Connection, name: str) -> int:
    """Insert artist by name; return id. Idempotent."""
    sort_name = make_sort_name(name)
    cur = conn.execute(
        "INSERT INTO artists(name, sort_name) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET sort_name = excluded.sort_name "
        "RETURNING id",
        (name, sort_name),
    )
    row = cur.fetchone()
    return int(row[0])


def upsert_album(
    conn: sqlite3.Connection,
    artist_id: int,
    title: str,
    year: Optional[int] = None,
) -> int:
    """Insert (or update year on existing) album for a given artist. Returns id."""
    cur = conn.execute(
        "INSERT INTO albums(title, artist_id, year) VALUES (?, ?, ?) "
        "ON CONFLICT(artist_id, title) DO UPDATE SET year = COALESCE(excluded.year, albums.year) "
        "RETURNING id",
        (title, artist_id, year),
    )
    row = cur.fetchone()
    return int(row[0])
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python -m pytest tests/test_library_scanner.py -v
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/scanner.py tests/test_library_scanner.py
git commit -m "feat(library): upsert helpers for artists + albums"
```

---

## Task 9: Track upsert + full scan walker

**Files:**
- Modify: `src/musi/library/scanner.py`
- Modify: `tests/test_library_scanner.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_library_scanner.py`:

```python
def test_full_scan_finds_all_audio_files(db_handle, synthetic_corpus):
    from musi.library.scanner import full_scan
    stats = full_scan(db_handle.connection, synthetic_corpus)
    assert stats.added == 4
    assert stats.updated == 0
    assert stats.skipped == 0
    assert stats.errors == 0

    total = db_handle.connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    assert total == 4


def test_full_scan_populates_artists_and_albums(db_handle, synthetic_corpus):
    from musi.library.scanner import full_scan
    full_scan(db_handle.connection, synthetic_corpus)

    artists = {r[0] for r in db_handle.connection.execute("SELECT name FROM artists").fetchall()}
    albums = {r[0] for r in db_handle.connection.execute("SELECT title FROM albums").fetchall()}

    assert artists == {"Radiohead", "The Beatles", "Björk"}
    assert albums == {"OK Computer", "Abbey Road", "Homogenic"}


def test_full_scan_track_metadata(db_handle, synthetic_corpus):
    from musi.library.scanner import full_scan
    full_scan(db_handle.connection, synthetic_corpus)

    row = db_handle.connection.execute(
        "SELECT title, track_no, year, format FROM tracks WHERE title = ?",
        ("Karma Police",),
    ).fetchone()
    assert row == ("Karma Police", 6, 1997, "mp3")


def test_full_scan_ignores_non_audio_files(db_handle, synthetic_corpus, tmp_path):
    # Add a non-audio file to the corpus root
    (synthetic_corpus / "readme.txt").write_text("hello")
    from musi.library.scanner import full_scan
    stats = full_scan(db_handle.connection, synthetic_corpus)
    # Same expected counts as before — text file not picked up
    assert stats.added == 4
    # Cleanup so subsequent test runs aren't affected
    (synthetic_corpus / "readme.txt").unlink(missing_ok=True)


def test_incremental_scan_skips_unchanged_files(db_handle, synthetic_corpus):
    from musi.library.scanner import full_scan
    s1 = full_scan(db_handle.connection, synthetic_corpus)
    assert s1.added == 4

    s2 = full_scan(db_handle.connection, synthetic_corpus)
    # Nothing changed, so everything should be skipped
    assert s2.added == 0
    assert s2.skipped == 4
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_scanner.py::test_full_scan_finds_all_audio_files -v
```

Expected: `AttributeError` or `ImportError` for `full_scan`.

- [ ] **Step 3: Extend scanner.py with walker + upsert_track + full_scan**

Replace `src/musi/library/scanner.py` with:

```python
"""Library scanner: walks the filesystem, upserts artists/albums/tracks.

Top-level entry: `full_scan(conn, root)`. Returns a ScanStats summary.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from musi.library.models import make_sort_name
from musi.library.tags import TagInfo, TagReadError, read_tags

_AUDIO_SUFFIXES = {".mp3", ".flac", ".alac", ".m4a", ".ogg", ".opus", ".wav"}

log = logging.getLogger(__name__)


@dataclass
class ScanStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def upsert_artist(conn: sqlite3.Connection, name: str) -> int:
    sort_name = make_sort_name(name)
    cur = conn.execute(
        "INSERT INTO artists(name, sort_name) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET sort_name = excluded.sort_name "
        "RETURNING id",
        (name, sort_name),
    )
    return int(cur.fetchone()[0])


def upsert_album(
    conn: sqlite3.Connection,
    artist_id: int,
    title: str,
    year: Optional[int] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO albums(title, artist_id, year) VALUES (?, ?, ?) "
        "ON CONFLICT(artist_id, title) DO UPDATE SET year = COALESCE(excluded.year, albums.year) "
        "RETURNING id",
        (title, artist_id, year),
    )
    return int(cur.fetchone()[0])


def _walk_audio(root: Path) -> Iterator[Path]:
    """Yield audio file paths under root, sorted for determinism."""
    if not root.is_dir():
        return
    for dirpath, _dirs, files in os.walk(root):
        for fname in sorted(files):
            p = Path(dirpath) / fname
            if p.suffix.lower() in _AUDIO_SUFFIXES:
                yield p


def _existing_track_mtime(conn: sqlite3.Connection, path: str) -> Optional[int]:
    row = conn.execute("SELECT mtime FROM tracks WHERE path = ?", (path,)).fetchone()
    return int(row[0]) if row else None


def _upsert_track(
    conn: sqlite3.Connection,
    path: str,
    tags: TagInfo,
    mtime: int,
    now: int,
) -> str:
    """Insert or update one track. Returns 'added' or 'updated'."""
    artist_id = upsert_artist(conn, tags.artist)
    album_id = upsert_album(conn, artist_id, tags.album, year=tags.year)

    existing = conn.execute("SELECT id FROM tracks WHERE path = ?", (path,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE tracks SET title=?, artist_id=?, album_id=?, track_no=?, disc_no=?, "
            "duration_ms=?, year=?, genre=?, bitrate=?, format=?, mtime=? WHERE path=?",
            (
                tags.title, artist_id, album_id, tags.track_no, tags.disc_no,
                tags.duration_ms, tags.year, tags.genre, tags.bitrate, tags.format,
                mtime, path,
            ),
        )
        return "updated"
    conn.execute(
        "INSERT INTO tracks(path, title, artist_id, album_id, track_no, disc_no, "
        "duration_ms, year, genre, bitrate, format, mtime, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            path, tags.title, artist_id, album_id, tags.track_no, tags.disc_no,
            tags.duration_ms, tags.year, tags.genre, tags.bitrate, tags.format,
            mtime, now,
        ),
    )
    return "added"


def full_scan(conn: sqlite3.Connection, root: Path) -> ScanStats:
    """Walk `root`, upserting all audio files. Skips unchanged (by mtime)."""
    stats = ScanStats()
    now = int(time.time())

    for path in _walk_audio(root):
        path_str = str(path)
        try:
            mtime = int(path.stat().st_mtime)
            existing_mtime = _existing_track_mtime(conn, path_str)
            if existing_mtime is not None and existing_mtime == mtime:
                stats.skipped += 1
                continue
            tags = read_tags(path)
            conn.execute("BEGIN")
            try:
                outcome = _upsert_track(conn, path_str, tags, mtime, now)
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
            if outcome == "added":
                stats.added += 1
            else:
                stats.updated += 1
        except TagReadError as e:
            log.warning("skipping %s: %s", path, e)
            stats.errors += 1
        except Exception:
            log.exception("scan failed for %s", path)
            stats.errors += 1

    return stats
```

- [ ] **Step 4: Run all scanner tests**

```bash
python -m pytest tests/test_library_scanner.py -v
```

Expected: 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/scanner.py tests/test_library_scanner.py
git commit -m "feat(library): full + incremental scanner"
```

---

## Task 10: Album art extraction (embedded → folder → fallback)

**Files:**
- Create: `src/musi/library/art.py`
- Create: `tests/test_library_art.py`

- [ ] **Step 1: Write failing test**

`tests/test_library_art.py`:

```python
"""Tests for album art extraction + pre-rendering."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from musi.library.art import (
    extract_album_art,
    render_thumbnail,
    render_blurred_backdrop,
    extract_palette,
    generate_fallback_gradient,
    ART_THUMB_SIZE,
    ART_BACKDROP_SIZE,
)


@pytest.fixture
def sample_image(tmp_path) -> Path:
    """Create a 600x600 image with distinct color zones for palette tests."""
    img = Image.new("RGB", (600, 600), (220, 80, 30))  # warm orange
    # Add a darker zone
    for x in range(0, 200):
        for y in range(0, 600):
            img.putpixel((x, y), (20, 30, 90))  # cool blue
    out = tmp_path / "cover.jpg"
    img.save(out, "JPEG", quality=85)
    return out


def test_extract_album_art_returns_none_when_no_source(tmp_path):
    # Empty album dir with no embedded art and no folder.jpg
    result = extract_album_art(tmp_path)
    assert result is None


def test_extract_album_art_finds_folder_jpg(tmp_path, sample_image):
    # Move the sample image to folder.jpg in the album dir
    folder_jpg = tmp_path / "folder.jpg"
    folder_jpg.write_bytes(sample_image.read_bytes())
    result = extract_album_art(tmp_path)
    assert result == folder_jpg


def test_extract_album_art_finds_cover_jpg(tmp_path, sample_image):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(sample_image.read_bytes())
    result = extract_album_art(tmp_path)
    assert result == cover


def test_render_thumbnail_produces_correct_size(tmp_path, sample_image):
    out_path = tmp_path / "thumb.jpg"
    render_thumbnail(sample_image, out_path)
    assert out_path.is_file()
    with Image.open(out_path) as img:
        assert img.size == ART_THUMB_SIZE


def test_render_blurred_backdrop_produces_correct_size(tmp_path, sample_image):
    out_path = tmp_path / "backdrop.jpg"
    render_blurred_backdrop(sample_image, out_path)
    assert out_path.is_file()
    with Image.open(out_path) as img:
        assert img.size == ART_BACKDROP_SIZE


def test_extract_palette_returns_three_hex_colors(sample_image):
    palette = extract_palette(sample_image)
    assert "primary" in palette
    assert "accent" in palette
    assert "text" in palette
    for v in palette.values():
        assert v.startswith("#")
        assert len(v) == 7  # #RRGGBB


def test_generate_fallback_gradient_is_deterministic(tmp_path):
    out_a = tmp_path / "a.jpg"
    out_b = tmp_path / "b.jpg"
    palette_a = generate_fallback_gradient("Artist", "Album", out_a)
    palette_b = generate_fallback_gradient("Artist", "Album", out_b)
    assert palette_a == palette_b
    assert out_a.read_bytes() == out_b.read_bytes()


def test_generate_fallback_gradient_size(tmp_path):
    out = tmp_path / "fallback.jpg"
    generate_fallback_gradient("Artist", "Album", out)
    with Image.open(out) as img:
        assert img.size == ART_BACKDROP_SIZE
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_art.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement art module**

`src/musi/library/art.py`:

```python
"""Album art pipeline: extract, resize, blur, palette-extract, fallback.

All work runs at scan time. The UI never invokes anything in this module.
"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageFilter

# Final output sizes — matches the 240x320 display.
ART_THUMB_SIZE: Tuple[int, int] = (160, 160)
ART_BACKDROP_SIZE: Tuple[int, int] = (240, 320)

_FOLDER_CANDIDATES = ("cover.jpg", "cover.jpeg", "cover.png",
                      "folder.jpg", "folder.jpeg", "folder.png",
                      "album.jpg", "front.jpg")


def extract_album_art(album_dir: Path) -> Optional[Path]:
    """Look in album_dir for a sidecar art file (cover.jpg / folder.jpg / ...).

    Embedded-tag extraction is in `extract_embedded_art` (separate function
    so caller can choose order: tag first, then sidecar fallback).
    """
    if not album_dir.is_dir():
        return None
    for name in _FOLDER_CANDIDATES:
        candidate = album_dir / name
        if candidate.is_file():
            return candidate
    return None


def extract_embedded_art(audio_path: Path) -> Optional[bytes]:
    """Return embedded album-art bytes from an audio file, or None."""
    import mutagen
    try:
        f = mutagen.File(audio_path)
    except Exception:
        return None
    if f is None:
        return None

    # MP3 / ID3 APIC
    if hasattr(f, "tags") and f.tags:
        for key in f.tags.keys():
            if key.startswith("APIC"):
                pic = f.tags[key]
                if hasattr(pic, "data"):
                    return pic.data
        # Some MP4 / M4A files store art in 'covr'
        if "covr" in f.tags:
            cov = f.tags["covr"][0]
            try:
                return bytes(cov)
            except Exception:
                pass
    # FLAC pictures
    if hasattr(f, "pictures") and f.pictures:
        return f.pictures[0].data

    return None


def _load_image(source: Path | bytes) -> Image.Image:
    if isinstance(source, (bytes, bytearray)):
        return Image.open(io.BytesIO(source)).convert("RGB")
    return Image.open(source).convert("RGB")


def render_thumbnail(source: Path | bytes, out_path: Path) -> None:
    """Resize source to ART_THUMB_SIZE and save as JPEG."""
    img = _load_image(source)
    img = img.copy()
    img.thumbnail((ART_THUMB_SIZE[0] * 2, ART_THUMB_SIZE[1] * 2), Image.LANCZOS)
    # center-crop to the exact thumb size
    w, h = img.size
    short = min(w, h)
    left = (w - short) // 2
    top = (h - short) // 2
    img = img.crop((left, top, left + short, top + short))
    img = img.resize(ART_THUMB_SIZE, Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=88)


def render_blurred_backdrop(source: Path | bytes, out_path: Path) -> None:
    """Produce a darkened, Gaussian-blurred 240x320 backdrop."""
    img = _load_image(source)

    # Scale to fill the backdrop (cover-fit)
    target_w, target_h = ART_BACKDROP_SIZE
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_size = (int(src_w * scale), int(src_h * scale))
    img = img.resize(new_size, Image.LANCZOS)

    # Center-crop to backdrop size
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    # Heavy blur + darken
    img = img.filter(ImageFilter.GaussianBlur(radius=18))
    enhancer = Image.new("RGB", img.size, (0, 0, 0))
    img = Image.blend(img, enhancer, alpha=0.45)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=82)


def extract_palette(source: Path | bytes) -> Dict[str, str]:
    """Extract primary/accent/text-on-bg hex colors from the source image."""
    img = _load_image(source)
    # Downsize to speed up the quantize
    img = img.copy()
    img.thumbnail((128, 128), Image.LANCZOS)
    quantized = img.quantize(colors=8, method=Image.MEDIANCUT)
    palette = quantized.getpalette()  # flat [r0,g0,b0, r1,g1,b1, ...]
    counts = quantized.getcolors() or []
    counts.sort(key=lambda c: c[0], reverse=True)

    def hex_of(idx: int) -> str:
        r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
        return f"#{r:02X}{g:02X}{b:02X}"

    if not counts:
        return {"primary": "#202020", "accent": "#808080", "text": "#FFFFFF"}

    primary = hex_of(counts[0][1])
    accent = hex_of(counts[1][1]) if len(counts) > 1 else primary
    # Choose white or black text based on the primary's luma
    r, g, b = palette[counts[0][1] * 3:counts[0][1] * 3 + 3]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    text = "#FFFFFF" if luma < 140 else "#101010"

    return {"primary": primary, "accent": accent, "text": text}


def generate_fallback_gradient(
    artist: str,
    album: str,
    out_path: Path,
) -> Dict[str, str]:
    """Deterministic gradient + palette for an artist+album with no art.

    Returns the palette dict (same shape as `extract_palette`).
    """
    h = hashlib.sha256(f"{artist}|{album}".encode("utf-8")).digest()
    hue1 = h[0] / 255.0
    hue2 = ((h[1] + h[2]) / 2) / 255.0

    def hsv_to_rgb(hue: float, s: float, v: float) -> Tuple[int, int, int]:
        i = int(hue * 6)
        f = hue * 6 - i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        r, g, b = [
            (v, t, p), (q, v, p), (p, v, t),
            (p, q, v), (t, p, v), (v, p, q),
        ][i % 6]
        return int(r * 255), int(g * 255), int(b * 255)

    color1 = hsv_to_rgb(hue1, 0.55, 0.45)
    color2 = hsv_to_rgb(hue2, 0.55, 0.20)

    w, hgt = ART_BACKDROP_SIZE
    img = Image.new("RGB", (w, hgt))
    for y in range(hgt):
        t = y / (hgt - 1)
        r = int(color1[0] * (1 - t) + color2[0] * t)
        g = int(color1[1] * (1 - t) + color2[1] * t)
        b = int(color1[2] * (1 - t) + color2[2] * t)
        for x in range(w):
            img.putpixel((x, y), (r, g, b))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=82)

    return {
        "primary": f"#{color1[0]:02X}{color1[1]:02X}{color1[2]:02X}",
        "accent": f"#{color2[0]:02X}{color2[1]:02X}{color2[2]:02X}",
        "text": "#FFFFFF",
    }
```

- [ ] **Step 4: Run art tests, verify pass**

```bash
python -m pytest tests/test_library_art.py -v
```

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/art.py tests/test_library_art.py
git commit -m "feat(library): album art pipeline (extract/resize/blur/palette/fallback)"
```

---

## Task 11: Integrate art pipeline into the scanner

**Files:**
- Modify: `src/musi/library/scanner.py`
- Modify: `tests/test_library_scanner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_library_scanner.py`:

```python
def test_full_scan_with_art_creates_assets(tmp_path, synthetic_corpus):
    from musi.library.config import LibraryConfig
    from musi.library.db import open_database
    from musi.library.scanner import full_scan

    cfg = LibraryConfig(
        music_root=synthetic_corpus,
        db_path=tmp_path / "library.db",
        art_dir=tmp_path / "art",
    )
    db = open_database(cfg)
    try:
        full_scan(db.connection, synthetic_corpus, art_dir=cfg.art_dir)

        # Every album should have a backdrop + palette filled in
        rows = db.connection.execute(
            "SELECT title, art_path, backdrop_path, color_primary FROM albums"
        ).fetchall()
        assert len(rows) == 3
        for title, art_path, backdrop_path, color_primary in rows:
            # Synthetic corpus has no embedded art, no folder.jpg — so we expect
            # the fallback gradient and a None art_path (no thumbnail) but a
            # filled backdrop_path
            assert art_path is None
            assert backdrop_path is not None
            assert (cfg.art_dir / Path(backdrop_path).name).is_file() or Path(backdrop_path).is_file()
            assert color_primary is not None
            assert color_primary.startswith("#")
    finally:
        db.close()
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_scanner.py::test_full_scan_with_art_creates_assets -v
```

Expected: `TypeError: full_scan() got an unexpected keyword argument 'art_dir'`.

- [ ] **Step 3: Update scanner.py to integrate art**

Modify the bottom of `src/musi/library/scanner.py`. Replace the `full_scan` function and add a new helper:

```python
def _ensure_album_art(
    conn: sqlite3.Connection,
    album_id: int,
    album_dir: Path,
    audio_path: Path,
    artist_name: str,
    album_title: str,
    art_dir: Optional[Path],
) -> None:
    """Generate/refresh art assets for an album if not already populated."""
    if art_dir is None:
        return

    row = conn.execute(
        "SELECT art_path, backdrop_path, color_primary FROM albums WHERE id=?",
        (album_id,),
    ).fetchone()
    if row is None:
        return
    art_path, backdrop_path, color_primary = row
    if backdrop_path is not None and color_primary is not None:
        return  # already populated

    from musi.library.art import (
        extract_album_art,
        extract_embedded_art,
        render_thumbnail,
        render_blurred_backdrop,
        extract_palette,
        generate_fallback_gradient,
    )

    thumb_dst = art_dir / f"album-{album_id}-thumb.jpg"
    backdrop_dst = art_dir / f"album-{album_id}-bg.jpg"

    # Source priority: embedded → sidecar → fallback
    source: Optional[Path | bytes] = extract_embedded_art(audio_path)
    if source is None:
        sidecar = extract_album_art(album_dir)
        if sidecar is not None:
            source = sidecar

    if source is not None:
        render_thumbnail(source, thumb_dst)
        render_blurred_backdrop(source, backdrop_dst)
        palette = extract_palette(source)
        conn.execute(
            "UPDATE albums SET art_path=?, backdrop_path=?, "
            "color_primary=?, color_accent=?, color_text=? WHERE id=?",
            (
                str(thumb_dst),
                str(backdrop_dst),
                palette["primary"],
                palette["accent"],
                palette["text"],
                album_id,
            ),
        )
    else:
        palette = generate_fallback_gradient(artist_name, album_title, backdrop_dst)
        conn.execute(
            "UPDATE albums SET art_path=NULL, backdrop_path=?, "
            "color_primary=?, color_accent=?, color_text=? WHERE id=?",
            (
                str(backdrop_dst),
                palette["primary"],
                palette["accent"],
                palette["text"],
                album_id,
            ),
        )


def full_scan(
    conn: sqlite3.Connection,
    root: Path,
    art_dir: Optional[Path] = None,
) -> ScanStats:
    """Walk `root`, upserting all audio files. Skips unchanged (by mtime).

    If `art_dir` is provided, the per-album art pipeline runs once per album
    (on first encounter of any track in that album).
    """
    stats = ScanStats()
    now = int(time.time())
    seen_albums: set[int] = set()

    for path in _walk_audio(root):
        path_str = str(path)
        try:
            mtime = int(path.stat().st_mtime)
            existing_mtime = _existing_track_mtime(conn, path_str)
            if existing_mtime is not None and existing_mtime == mtime:
                stats.skipped += 1
                continue
            tags = read_tags(path)
            conn.execute("BEGIN")
            try:
                artist_id = upsert_artist(conn, tags.artist)
                album_id = upsert_album(conn, artist_id, tags.album, year=tags.year)
                outcome = _upsert_track_with_ids(
                    conn, path_str, tags, mtime, now, artist_id, album_id,
                )
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise

            if album_id not in seen_albums:
                seen_albums.add(album_id)
                _ensure_album_art(
                    conn=conn,
                    album_id=album_id,
                    album_dir=path.parent,
                    audio_path=path,
                    artist_name=tags.artist,
                    album_title=tags.album,
                    art_dir=art_dir,
                )

            if outcome == "added":
                stats.added += 1
            else:
                stats.updated += 1
        except TagReadError as e:
            log.warning("skipping %s: %s", path, e)
            stats.errors += 1
        except Exception:
            log.exception("scan failed for %s", path)
            stats.errors += 1

    return stats


def _upsert_track_with_ids(
    conn: sqlite3.Connection,
    path: str,
    tags: TagInfo,
    mtime: int,
    now: int,
    artist_id: int,
    album_id: int,
) -> str:
    existing = conn.execute("SELECT id FROM tracks WHERE path = ?", (path,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE tracks SET title=?, artist_id=?, album_id=?, track_no=?, disc_no=?, "
            "duration_ms=?, year=?, genre=?, bitrate=?, format=?, mtime=? WHERE path=?",
            (
                tags.title, artist_id, album_id, tags.track_no, tags.disc_no,
                tags.duration_ms, tags.year, tags.genre, tags.bitrate, tags.format,
                mtime, path,
            ),
        )
        return "updated"
    conn.execute(
        "INSERT INTO tracks(path, title, artist_id, album_id, track_no, disc_no, "
        "duration_ms, year, genre, bitrate, format, mtime, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            path, tags.title, artist_id, album_id, tags.track_no, tags.disc_no,
            tags.duration_ms, tags.year, tags.genre, tags.bitrate, tags.format,
            mtime, now,
        ),
    )
    return "added"


# The original _upsert_track is now unused; delete it. The function above is
# the replacement. We keep upsert_artist / upsert_album exported for testing.
```

> **Important:** delete the old `_upsert_track` function from the file — it's been replaced by `_upsert_track_with_ids`. Keep `upsert_artist` and `upsert_album` exported.

- [ ] **Step 4: Run all scanner tests**

```bash
python -m pytest tests/test_library_scanner.py -v
```

Expected: 12 PASS (11 prior + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/scanner.py tests/test_library_scanner.py
git commit -m "feat(library): scanner integrates art pipeline per album"
```

---

## Task 12: Service entry point (long-running watcher)

**Files:**
- Create: `src/musi/library/service.py`
- Create: `tests/test_library_service.py`

The service runs forever: do a full scan on startup, then watch `/music` with watchdog and incrementally rescan on changes. Filesystem events are batched (no rescan storm on a big rsync from USB sync mode).

- [ ] **Step 1: Write failing test**

`tests/test_library_service.py`:

```python
"""Tests for the long-running library service.

We don't actually run the inotify loop in tests — we exercise the inner
functions directly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from musi.library.config import LibraryConfig
from musi.library.service import run_one_scan_cycle


@pytest.fixture
def library_config(tmp_path, synthetic_corpus):
    return LibraryConfig(
        music_root=synthetic_corpus,
        db_path=tmp_path / "library.db",
        art_dir=tmp_path / "art",
    )


def test_run_one_scan_cycle_populates_db(library_config):
    stats = run_one_scan_cycle(library_config)
    assert stats.added == 4
    assert stats.errors == 0
    # DB exists
    assert library_config.db_path.is_file()


def test_run_one_scan_cycle_idempotent(library_config):
    first = run_one_scan_cycle(library_config)
    second = run_one_scan_cycle(library_config)
    assert first.added == 4
    assert second.added == 0
    assert second.skipped == 4
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_service.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement service**

`src/musi/library/service.py`:

```python
"""Long-running library service.

Behavior:
  - On start, run a full scan.
  - Then watch `MUSI_MUSIC_ROOT` with watchdog. On any modification,
    debounce for 2 seconds, then re-scan.
  - SIGTERM/SIGINT triggers a clean shutdown.

`run_one_scan_cycle` is a convenience for tests + the CLI's `scan` command.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path

from musi.library.config import LibraryConfig
from musi.library.db import open_database
from musi.library.scanner import ScanStats, full_scan

log = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 2.0


def run_one_scan_cycle(config: LibraryConfig) -> ScanStats:
    """Open DB, run one full scan, return stats."""
    db = open_database(config)
    try:
        return full_scan(db.connection, config.music_root, art_dir=config.art_dir)
    finally:
        db.close()


def run_service(config: LibraryConfig) -> None:
    """Run the service: initial scan + watch loop. Blocks until SIGTERM."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    stop_event = threading.Event()
    debounce_event = threading.Event()

    def _on_signal(signum, frame):
        log.info("received signal %d, shutting down", signum)
        stop_event.set()
        debounce_event.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    log.info("musi-library starting up; initial scan...")
    stats = run_one_scan_cycle(config)
    log.info(
        "initial scan complete: added=%d updated=%d skipped=%d errors=%d",
        stats.added, stats.updated, stats.skipped, stats.errors,
    )

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            debounce_event.set()

    observer = Observer()
    if config.music_root.is_dir():
        observer.schedule(_Handler(), str(config.music_root), recursive=True)
        observer.start()
    else:
        log.warning("music root %s does not exist; watcher idle", config.music_root)

    try:
        while not stop_event.is_set():
            triggered = debounce_event.wait(timeout=10.0)
            if not triggered:
                continue
            # Debounce: wait for the burst to settle.
            while True:
                debounce_event.clear()
                if stop_event.is_set():
                    break
                if not debounce_event.wait(timeout=_DEBOUNCE_SECONDS):
                    break
            if stop_event.is_set():
                break
            log.info("filesystem change detected; rescanning...")
            stats = run_one_scan_cycle(config)
            log.info(
                "rescan: added=%d updated=%d skipped=%d errors=%d",
                stats.added, stats.updated, stats.skipped, stats.errors,
            )
    finally:
        observer.stop()
        observer.join(timeout=5.0)
        log.info("musi-library stopped")
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python -m pytest tests/test_library_service.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/musi/library/service.py tests/test_library_service.py
git commit -m "feat(library): service entry with initial scan + watchdog"
```

---

## Task 13: CLI (`musi library scan`, `musi library list`, `musi library search`)

**Files:**
- Create: `src/musi/library/cli.py`
- Modify: `src/musi/__main__.py`
- Create: `tests/test_library_cli.py`

- [ ] **Step 1: Write failing test**

`tests/test_library_cli.py`:

```python
"""Tests for the library CLI subcommand routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from musi.library.cli import cli_main


def test_cli_scan_populates_db(tmp_path, synthetic_corpus, monkeypatch, capsys):
    monkeypatch.setenv("MUSI_MUSIC_ROOT", str(synthetic_corpus))
    monkeypatch.setenv("MUSI_DB_PATH", str(tmp_path / "library.db"))
    monkeypatch.setenv("MUSI_ART_DIR", str(tmp_path / "art"))

    rc = cli_main(["scan"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "added" in out
    assert (tmp_path / "library.db").is_file()


def test_cli_search_finds_track(tmp_path, synthetic_corpus, monkeypatch, capsys):
    monkeypatch.setenv("MUSI_MUSIC_ROOT", str(synthetic_corpus))
    monkeypatch.setenv("MUSI_DB_PATH", str(tmp_path / "library.db"))
    monkeypatch.setenv("MUSI_ART_DIR", str(tmp_path / "art"))

    cli_main(["scan"])
    capsys.readouterr()  # discard scan output

    rc = cli_main(["search", "karma"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Karma Police" in out


def test_cli_list_artists(tmp_path, synthetic_corpus, monkeypatch, capsys):
    monkeypatch.setenv("MUSI_MUSIC_ROOT", str(synthetic_corpus))
    monkeypatch.setenv("MUSI_DB_PATH", str(tmp_path / "library.db"))
    monkeypatch.setenv("MUSI_ART_DIR", str(tmp_path / "art"))

    cli_main(["scan"])
    capsys.readouterr()

    rc = cli_main(["list", "artists"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Radiohead" in out
    assert "The Beatles" in out


def test_cli_unknown_command_returns_nonzero(capsys):
    rc = cli_main(["bogus"])
    assert rc != 0
```

- [ ] **Step 2: Run, verify failure**

```bash
python -m pytest tests/test_library_cli.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement CLI**

`src/musi/library/cli.py`:

```python
"""Library CLI: `python -m musi library <subcommand>`.

Subcommands:
  scan                          One-shot full scan
  service                       Long-running service (watchdog loop)
  list artists | albums | tracks [--limit N]
  search <query> [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from musi.library.config import LibraryConfig
from musi.library.db import open_database
from musi.library.service import run_one_scan_cycle, run_service


def _cmd_scan(_args) -> int:
    cfg = LibraryConfig.from_env()
    stats = run_one_scan_cycle(cfg)
    print(
        f"scan complete: added={stats.added} updated={stats.updated} "
        f"skipped={stats.skipped} errors={stats.errors}"
    )
    return 0 if stats.errors == 0 else 1


def _cmd_service(_args) -> int:
    cfg = LibraryConfig.from_env()
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_service(cfg)
    return 0


def _cmd_list(args) -> int:
    cfg = LibraryConfig.from_env()
    db = open_database(cfg)
    try:
        c = db.connection
        if args.target == "artists":
            rows = c.execute(
                "SELECT name FROM artists ORDER BY sort_name LIMIT ?", (args.limit,)
            ).fetchall()
            for (name,) in rows:
                print(name)
        elif args.target == "albums":
            rows = c.execute(
                "SELECT al.title, ar.name FROM albums al "
                "JOIN artists ar ON ar.id = al.artist_id "
                "ORDER BY ar.sort_name, al.title LIMIT ?",
                (args.limit,),
            ).fetchall()
            for title, artist in rows:
                print(f"{artist} — {title}")
        elif args.target == "tracks":
            rows = c.execute(
                "SELECT t.title, ar.name, al.title FROM tracks t "
                "JOIN artists ar ON ar.id = t.artist_id "
                "JOIN albums al ON al.id = t.album_id "
                "ORDER BY ar.sort_name, al.title, t.disc_no, t.track_no LIMIT ?",
                (args.limit,),
            ).fetchall()
            for title, artist, album in rows:
                print(f"{artist} — {album} — {title}")
        else:
            print(f"unknown list target: {args.target}", file=sys.stderr)
            return 2
        return 0
    finally:
        db.close()


def _cmd_search(args) -> int:
    cfg = LibraryConfig.from_env()
    db = open_database(cfg)
    try:
        # FTS5 likes its query in its own syntax; we wrap each token with a *
        # for prefix matching, which is more forgiving for partial queries.
        terms = " ".join(f'{tok}*' for tok in args.query.strip().split())
        rows = db.connection.execute(
            "SELECT t.title, ar.name, al.title "
            "FROM tracks_fts ft "
            "JOIN tracks t ON t.id = ft.rowid "
            "JOIN artists ar ON ar.id = t.artist_id "
            "JOIN albums al ON al.id = t.album_id "
            "WHERE tracks_fts MATCH ? LIMIT ?",
            (terms, args.limit),
        ).fetchall()
        for title, artist, album in rows:
            print(f"{artist} — {album} — {title}")
        return 0
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="musi library")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Run a one-shot full scan")
    sub.add_parser("service", help="Run as a long-lived service with watchdog")

    p_list = sub.add_parser("list", help="List artists, albums, or tracks")
    p_list.add_argument("target", choices=("artists", "albums", "tracks"))
    p_list.add_argument("--limit", type=int, default=50)

    p_search = sub.add_parser("search", help="Full-text search across the library")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)

    return p


def cli_main(argv: List[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "scan": _cmd_scan,
        "service": _cmd_service,
        "list": _cmd_list,
        "search": _cmd_search,
    }
    handler = handlers.get(args.command)
    if handler is None:
        return 1
    return handler(args)
```

- [ ] **Step 4: Wire the CLI into `python -m musi`**

Modify `src/musi/__main__.py` — full replacement:

```python
"""Entry point for `python -m musi <subcommand>`."""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m musi <command> [<args>...]")
        print("Commands:")
        print("  hello                 Run the hello-world pygame app")
        print("  library <subcommand>  Library indexer CLI")
        return 1

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "hello":
        from musi.hello import run
        return run()

    if cmd == "library":
        from musi.library.cli import cli_main
        return cli_main(rest)

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: End-to-end smoke test from the shell**

```bash
mkdir -p ~/musi-test-corpus
python -c "
from pathlib import Path
from tests.helpers.audio_fixtures import default_specs, make_corpus
make_corpus(Path.home() / 'musi-test-corpus', default_specs())
"
export MUSI_MUSIC_ROOT=~/musi-test-corpus
python -m musi library scan
python -m musi library list artists
python -m musi library list albums
python -m musi library search "karma"
```

Expected:
- scan reports 4 added
- list artists shows Björk, Radiohead, The Beatles
- list albums shows the three albums
- search for "karma" returns the Karma Police track

- [ ] **Step 7: Commit**

```bash
git add src/musi/library/cli.py src/musi/__main__.py tests/test_library_cli.py
git commit -m "feat(library): CLI (scan, service, list, search)"
```

---

## Task 14: Performance test — 1,000 synthetic tracks

We can't easily generate 10,000 audio files in a test (would take minutes per run). Instead, generate 1,000 once and validate the scan completes in a reasonable time + memory budget. This is a "perf gate" test rather than functional.

**Files:**
- Create: `tests/test_library_perf.py`

- [ ] **Step 1: Write the perf test**

`tests/test_library_perf.py`:

```python
"""Perf gate: 1,000 synthetic tracks must scan in under 60 seconds.

Marked slow; opt in with: pytest -m slow
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from musi.library.config import LibraryConfig
from musi.library.scanner import full_scan
from musi.library.db import open_database
from tests.helpers.audio_fixtures import FakeTrackSpec, make_corpus


pytestmark = pytest.mark.slow


@pytest.fixture(scope="session")
def large_corpus(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("musi-large")
    specs = []
    for artist_i in range(20):       # 20 artists
        for album_i in range(5):     # 5 albums each
            for track_i in range(10):  # 10 tracks each → 1000 total
                specs.append(
                    FakeTrackSpec(
                        relative_path=f"Artist{artist_i:02d}/Album{album_i:02d}/{track_i:02d}.mp3",
                        title=f"Track {track_i:02d}",
                        artist=f"Artist{artist_i:02d}",
                        album=f"Album{album_i:02d}",
                        track_no=track_i,
                        year=2000 + album_i,
                    )
                )
    make_corpus(root, specs)
    return root


def test_scan_1000_tracks_under_60_seconds(tmp_path, large_corpus):
    cfg = LibraryConfig(
        music_root=large_corpus,
        db_path=tmp_path / "library.db",
        art_dir=tmp_path / "art",
    )
    db = open_database(cfg)
    try:
        start = time.monotonic()
        stats = full_scan(db.connection, large_corpus, art_dir=cfg.art_dir)
        elapsed = time.monotonic() - start
        assert stats.added == 1000
        assert stats.errors == 0
        assert elapsed < 60.0, f"scan took {elapsed:.1f}s (budget 60s)"
        print(f"\n1,000 track scan: {elapsed:.2f}s")
    finally:
        db.close()
```

- [ ] **Step 2: Register the `slow` marker**

Update `pyproject.toml` — find the `[tool.pytest.ini_options]` block and add:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "slow: long-running tests (opt in with -m slow)",
]
```

- [ ] **Step 3: Run the perf test**

```bash
python -m pytest tests/test_library_perf.py -v -m slow -s
```

Expected: PASS, with the elapsed time printed. On a modern dev PC, ~1,000 tracks should scan in well under 30 seconds even with art generation. On a Pi Zero 2 W (later) expect ~3-5x slower.

If it fails (>60s), this is a sign the scan or art pipeline needs profiling — but at this point in development that's a future-Plan concern, not blocking.

- [ ] **Step 4: Commit**

```bash
git add tests/test_library_perf.py pyproject.toml
git commit -m "test(library): perf gate for 1,000-track scan"
```

---

## Task 15: User docs and wrap up

**Files:**
- Create: `docs/LIBRARY.md`
- Modify: `README.md`

- [ ] **Step 1: Write `docs/LIBRARY.md`**

```markdown
# musi-library

The library indexer service. Walks your music collection, reads tags,
extracts album art, pre-renders display assets, and stores everything in
SQLite for the UI to query.

## Configuration

Three environment variables:

| Var | Default (dev) | Default (prod) | Meaning |
|---|---|---|---|
| `MUSI_MUSIC_ROOT` | `~/music` | `/music` | Where to scan |
| `MUSI_DB_PATH` | `~/.local/share/musi/library.db` | `/var/lib/musi/library.db` | SQLite database file |
| `MUSI_ART_DIR` | `~/.local/share/musi/art` | `/var/lib/musi/art` | Pre-rendered art output |

The defaults follow the XDG Base Directory spec on Linux.

## CLI

```
python -m musi library scan                 # One-shot full scan
python -m musi library service              # Long-running service with watchdog
python -m musi library list artists         # List artists
python -m musi library list albums          # List albums
python -m musi library list tracks --limit 100
python -m musi library search "radiohead"   # FTS5 search across artists/albums/tracks
```

## What the scan produces

For each album:
- `art-<album_id>-thumb.jpg`: 160×160 album thumbnail (if art was found)
- `art-<album_id>-bg.jpg`: 240×320 blurred backdrop (always — falls back to a deterministic gradient if no art was found)
- Three hex colors stored in the DB: `color_primary`, `color_accent`, `color_text` (for art-driven UI theming)

## Schema

See `src/musi/library/migrations/*.sql` for the canonical schema. Highlights:

- `artists`, `albums`, `tracks` with surrogate primary keys
- `tracks_fts` virtual table (FTS5) with sync triggers
- `play_history` for "recently played"
- `settings` k/v store
- `schema_version` for the migration runner

## Incremental scans

The scanner uses file mtime to skip unchanged tracks. The cost of a "no-op"
rescan over 1,000 tracks is sub-second. A full first scan with art generation
is the only expensive operation — budget ~1ms per track on a dev PC, ~5ms per
track on Pi Zero 2 W.
```

- [ ] **Step 2: Update README**

Append to `README.md`:

```markdown
## Plan 02 — Library indexer complete (v0.2)

- SQLite schema with FTS5 search
- Mutagen-based tag reader
- Filesystem walker with mtime-based incremental scans
- Album art pipeline: extract → thumbnail → blurred backdrop → palette
- Fallback gradient for albums without art
- Long-running service with watchdog filesystem watcher
- CLI: scan, service, list, search

Next: Plan 03 — UI core (nav stack + render loop) with a keyboard-input
adapter so the UI can be developed on a desktop PC.
```

- [ ] **Step 3: Commit + tag**

```bash
git add docs/LIBRARY.md README.md
git commit -m "docs: library service guide; v0.2 complete"
git tag v0.2
```

---

## Definition of done for Plan 02

✅ All tests pass on Linux dev PC: `python -m pytest -v`
✅ The slow perf test passes: `python -m pytest -v -m slow -s`
✅ Pointing `MUSI_MUSIC_ROOT` at a real music directory and running `python -m musi library scan` populates the DB
✅ `python -m musi library search <query>` returns FTS5-matched results
✅ Album art assets (thumb + backdrop) appear in `$MUSI_ART_DIR` after scan
✅ Albums without art get a deterministic gradient backdrop and palette
✅ `python -m musi library service` runs forever; touching a file in the music dir triggers a rescan within ~2 seconds
✅ Repo tagged v0.2

You now have a complete library indexing layer. Plan 03 (UI core) will read from this DB and render screens.
