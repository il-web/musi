CREATE TABLE IF NOT EXISTS artists (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS albums (
    id            INTEGER PRIMARY KEY,
    artist_id     INTEGER NOT NULL REFERENCES artists(id),
    title         TEXT NOT NULL,
    year          INTEGER,
    art_path      TEXT,
    backdrop_path TEXT,
    palette       TEXT,
    UNIQUE(artist_id, title)
);

CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY,
    album_id     INTEGER NOT NULL REFERENCES albums(id),
    artist_id    INTEGER NOT NULL REFERENCES artists(id),
    path         TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    track_number INTEGER,
    disc_number  INTEGER DEFAULT 1,
    duration     REAL,
    file_mtime   REAL
);

CREATE TABLE IF NOT EXISTS play_history (
    id        INTEGER PRIMARY KEY,
    track_id  INTEGER NOT NULL REFERENCES tracks(id),
    played_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_tracks_album       ON tracks(album_id);
CREATE INDEX IF NOT EXISTS idx_tracks_artist      ON tracks(artist_id);
CREATE INDEX IF NOT EXISTS idx_albums_artist      ON albums(artist_id);
CREATE INDEX IF NOT EXISTS idx_play_history_track ON play_history(track_id);
CREATE INDEX IF NOT EXISTS idx_play_history_time  ON play_history(played_at);
