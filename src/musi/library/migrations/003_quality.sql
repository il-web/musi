-- Audio quality per track (library/quality.py): shown as tags on the album page.
ALTER TABLE tracks ADD COLUMN codec       TEXT;
ALTER TABLE tracks ADD COLUMN bitrate     INTEGER;   -- kbps
ALTER TABLE tracks ADD COLUMN sample_rate INTEGER;   -- Hz
ALTER TABLE tracks ADD COLUMN bit_depth   INTEGER;
ALTER TABLE tracks ADD COLUMN channels    INTEGER;
