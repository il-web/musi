"""Audio quality tags + sharper album covers."""
import os
import sqlite3
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest
from PIL import Image

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library import art, quality


def T(codec, **kw):
    return {"codec": codec, "title": kw.pop("title", "Song"), "path": kw.pop("path", "/m/a"), **kw}


# ── album tags ────────────────────────────────────────────────────────────────

def test_hires_flac():
    b = quality.badges([T("FLAC", bit_depth=24, sample_rate=96000, channels=2)] * 3)
    assert b == [("FLAC", "format"), ("Hi-Res 24-bit / 96 kHz", "hires")]


def test_cd_quality_flac_is_lossless():
    b = quality.badges([T("FLAC", bit_depth=16, sample_rate=44100)])
    assert b == [("FLAC", "format"), ("Lossless 16-bit / 44.1 kHz", "lossless")]


def test_mp3_shows_its_bitrate():
    b = quality.badges([T("MP3", bitrate=320), T("MP3", bitrate=320), T("MP3", bitrate=256)])
    assert b == [("MP3", "format"), ("320 kbps", "lossy")]


def test_dolby_and_surround():
    assert quality.badges([T("AC-3", channels=6)]) == [("Dolby Digital", "dolby"), ("5.1", "surround")]
    eac3 = [T("E-AC-3", channels=8, title="Song (Dolby Atmos)")]
    assert quality.badges(eac3) == [("Dolby Atmos", "dolby"), ("7.1", "surround")]
    assert quality.badges([T("E-AC-3", channels=6)])[0] == ("Dolby Digital Plus", "dolby")


def test_mixed_album_lists_both_formats_and_unknown_is_empty():
    b = quality.badges([T("FLAC", bit_depth=16, sample_rate=44100)] * 3 + [T("MP3", bitrate=320)])
    assert [x[0] for x in b][:2] == ["FLAC", "MP3"]
    assert quality.badges([{"codec": None}]) == []


def test_from_subsonic():
    q = quality.from_subsonic({"suffix": "flac", "bitRate": 2100, "samplingRate": 96000,
                               "bitDepth": 24, "channelCount": 2})
    assert q == {"codec": "FLAC", "bitrate": 2100, "sample_rate": 96000,
                 "bit_depth": 24, "channels": 2}
    assert quality.from_subsonic({"suffix": "m4a", "bitRate": 256})["codec"] == "AAC"
    assert quality.from_subsonic({"suffix": "m4a", "bitRate": 900})["codec"] == "ALAC"
    assert quality.from_subsonic({"suffix": "eac3"})["codec"] == "E-AC-3"


def test_probe_reads_a_real_wav(tmp_path):
    import wave
    p = tmp_path / "t.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)          # 24-bit
        w.setframerate(96000)
        w.writeframes(b"\0" * 6 * 960)
    q = quality.probe(p)
    assert q["codec"] == "WAV" and q["sample_rate"] == 96000
    assert q["bit_depth"] == 24 and q["channels"] == 2


def test_dolby_files_are_scanned():
    from musi.library.tags import is_audio_file
    for ext in (".ac3", ".eac3", ".aiff", ".dsf"):
        assert is_audio_file(Path("x" + ext)), ext


# ── covers ────────────────────────────────────────────────────────────────────

def _album(tmp_path, colour=(200, 30, 60)):
    d = tmp_path / "album"
    d.mkdir()
    img = Image.new("RGB", (800, 800), colour)
    for x in range(0, 800, 40):                      # detail that blurs if upscaled
        img.paste((255, 255, 255), (x, 0, x + 4, 800))
    img.save(d / "cover.jpg")
    track = d / "01.mp3"
    track.write_bytes(b"")
    return track


def test_new_covers_are_full_panel_width(tmp_path):
    track = _album(tmp_path)
    thumb, _, _ = art.process_art(track, tmp_path / "art", "A::B")
    assert Image.open(thumb).size == (320, 320)


def test_old_small_cover_is_upgraded_from_the_albums_own_art(tmp_path):
    track = _album(tmp_path)
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    thumb = art_dir / f"{art.album_slug('A::B')}_thumb.jpg"
    src = Image.open(track.parent / "cover.jpg")
    art._crop_square(src).resize((160, 160), Image.LANCZOS).save(thumb, "JPEG", quality=85)
    assert art.upgrade_thumb(track, art_dir, "A::B") is True
    assert Image.open(thumb).size == (320, 320)
    assert art.upgrade_thumb(track, art_dir, "A::B") is False     # already sharp


def test_a_cover_someone_picked_is_never_replaced(tmp_path):
    track = _album(tmp_path)
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    thumb = art_dir / f"{art.album_slug('A::B')}_thumb.jpg"
    Image.new("RGB", (160, 160), (10, 200, 10)).save(thumb)      # a different picture
    assert art.upgrade_thumb(track, art_dir, "A::B") is False
    assert Image.open(thumb).size == (160, 160)


def test_scan_fills_quality_and_upgrades_once(tmp_path, monkeypatch):
    from musi.library import scanner
    from musi.library.db import run_migrations
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute("INSERT INTO artists (id, name) VALUES (1, 'A')")
    conn.execute("INSERT INTO albums (id, artist_id, title) VALUES (1, 1, 'B')")
    conn.execute("INSERT INTO tracks (album_id, artist_id, path, title) VALUES (1, 1, ?, 'x')",
                 (str(tmp_path / "x.flac"),))
    monkeypatch.setattr(quality, "probe", lambda p: {"codec": "FLAC", "bit_depth": 24,
                                                     "sample_rate": 96000})
    assert scanner._fill_quality(conn) == 1
    assert scanner._fill_quality(conn) == 0                       # probed once
    row = conn.execute("SELECT codec, bit_depth FROM tracks").fetchone()
    assert (row["codec"], row["bit_depth"]) == ("FLAC", 24)

    art_dir = tmp_path / "art"
    art_dir.mkdir()
    calls = []
    monkeypatch.setattr(art, "upgrade_thumb", lambda *a: calls.append(a) or True)
    assert scanner._upgrade_art(conn, art_dir) == 1
    assert scanner._upgrade_art(conn, art_dir) == 0               # marker: once
    assert len(calls) == 1


def test_covers_are_resized_smoothly_and_opaque(tmp_path):
    from musi.player import art_cache
    p = tmp_path / "c.jpg"
    Image.new("RGB", (320, 320), (200, 30, 60)).save(p)
    s = art_cache.load_surface(str(p), (93, 93))
    assert s.get_size() == (93, 93) and not (s.get_flags() & pygame.SRCALPHA)


def test_album_page_draws_its_tags():
    from musi.player.mpd_client import PlayerStatus
    from musi.player.screens import album as album_mod

    s = album_mod.AlbumScreen.__new__(album_mod.AlbumScreen)
    s._meta_surf = pygame.Surface((80, 12))
    s._badge_surfs = [album_mod._badge("FLAC", "format"),
                      album_mod._badge("Hi-Res 24-bit / 96 kHz", "hires")]
    surf = pygame.Surface((320, 480))
    s._draw_meta_row(surf, 197)                    # fits: all drawn, centred
    s._badge_surfs = [album_mod._badge("X" * 30, "format")] * 4
    s._draw_meta_row(surf, 197)                    # too wide: tail dropped, no crash
