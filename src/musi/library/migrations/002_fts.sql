CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
    title,
    album,
    artist,
    content='',
    contentless_delete=1
);

CREATE TRIGGER IF NOT EXISTS tracks_fts_insert
AFTER INSERT ON tracks BEGIN
    INSERT INTO tracks_fts(rowid, title, album, artist)
    SELECT NEW.id, NEW.title, al.title, ar.name
    FROM albums al JOIN artists ar ON al.artist_id = ar.id
    WHERE al.id = NEW.album_id;
END;

CREATE TRIGGER IF NOT EXISTS tracks_fts_delete
AFTER DELETE ON tracks BEGIN
    DELETE FROM tracks_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS tracks_fts_update
AFTER UPDATE ON tracks BEGIN
    DELETE FROM tracks_fts WHERE rowid = OLD.id;
    INSERT INTO tracks_fts(rowid, title, album, artist)
    SELECT NEW.id, NEW.title, al.title, ar.name
    FROM albums al JOIN artists ar ON al.artist_id = ar.id
    WHERE al.id = NEW.album_id;
END;
