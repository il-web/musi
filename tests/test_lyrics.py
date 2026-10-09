"""LRCLIB lyrics — LRC parsing, line tracking, disk cache, fetch behaviour.

No test here touches the network: the HTTP layer is injected.
"""
import json
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pytest

from musi.library import lyrics as ly

_LRC = """[ar:Band]
[00:12.30] First line
[00:15.00]Second line
[01:02.50] Third line
"""


# ── LRC parsing ───────────────────────────────────────────────────────────────

def test_parse_lrc_reads_timestamps_and_text():
    lines = ly.parse_lrc(_LRC)
    assert lines == [(12.30, "First line"),
                     (15.00, "Second line"),
                     (62.50, "Third line")]


def test_parse_lrc_skips_metadata_tags():
    assert all(t > 0 for t, _ in ly.parse_lrc(_LRC))


def test_parse_lrc_handles_repeated_timestamps_on_one_line():
    lines = ly.parse_lrc("[00:01.00][00:31.00] Chorus")
    assert lines == [(1.0, "Chorus"), (31.0, "Chorus")]


def test_parse_lrc_sorts_by_time():
    lines = ly.parse_lrc("[00:30.00] Later\n[00:10.00] Earlier")
    assert [t for t, _ in lines] == [10.0, 30.0]


def test_parse_lrc_keeps_blank_interludes():
    lines = ly.parse_lrc("[00:05.00]\n[00:09.00] Words")
    assert lines[0] == (5.0, "")


def test_parse_lrc_of_junk_is_empty():
    assert ly.parse_lrc("no timestamps here") == []


# ── current line ──────────────────────────────────────────────────────────────

def test_active_index_before_the_first_line_is_minus_one():
    lines = ly.parse_lrc(_LRC)
    assert ly.active_index(lines, 0.0) == -1


def test_active_index_tracks_elapsed():
    lines = ly.parse_lrc(_LRC)
    assert ly.active_index(lines, 12.30) == 0
    assert ly.active_index(lines, 14.99) == 0
    assert ly.active_index(lines, 15.00) == 1
    assert ly.active_index(lines, 999.0) == 2


def test_active_index_on_empty_lines():
    assert ly.active_index([], 10.0) == -1


# ── cache ─────────────────────────────────────────────────────────────────────

def test_cache_path_is_stable_and_scoped_to_the_track(tmp_path):
    a = ly.cache_path(tmp_path, "Band", "Song")
    assert a == ly.cache_path(tmp_path, "Band", "Song")
    assert a != ly.cache_path(tmp_path, "Band", "Other")
    assert a.parent == tmp_path


def test_cache_key_ignores_case_and_padding(tmp_path):
    assert (ly.cache_path(tmp_path, "Band", "Song")
            == ly.cache_path(tmp_path, " band ", "SONG"))


def test_get_lyrics_writes_a_cache_file(tmp_path):
    def fake_get(url, **kw):
        return json.dumps({"syncedLyrics": _LRC, "plainLyrics": "",
                           "instrumental": False}).encode()

    res = ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    assert res.found and res.synced
    assert ly.cache_path(tmp_path, "Band", "Song").exists()


def test_second_call_uses_the_cache_and_does_not_hit_the_network(tmp_path):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return json.dumps({"syncedLyrics": _LRC, "plainLyrics": "",
                           "instrumental": False}).encode()

    ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    res = ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    assert len(calls) == 1
    assert res.found and len(res.lines) == 3


def test_plain_only_result_is_kept_unsynced(tmp_path):
    def fake_get(url, **kw):
        return json.dumps({"syncedLyrics": "", "plainLyrics": "just words",
                           "instrumental": False}).encode()

    res = ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    assert res.found is True
    assert res.synced is False
    assert res.plain == "just words"


def test_instrumental_is_reported_not_treated_as_missing(tmp_path):
    def fake_get(url, **kw):
        return json.dumps({"syncedLyrics": "", "plainLyrics": "",
                           "instrumental": True}).encode()

    res = ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    assert res.instrumental is True
    assert res.found is False


# ── misses ────────────────────────────────────────────────────────────────────

def test_a_miss_is_cached_so_the_screen_does_not_refetch(tmp_path):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return None                       # 404 from LRCLIB

    assert ly.get_lyrics(tmp_path, "B", "S", "A", 9.0, get=fake_get).found is False
    assert ly.get_lyrics(tmp_path, "B", "S", "A", 9.0, get=fake_get).found is False
    assert len(calls) == 1


def test_force_retries_a_cached_miss(tmp_path):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            return None
        return json.dumps({"syncedLyrics": _LRC, "plainLyrics": "",
                           "instrumental": False}).encode()

    ly.get_lyrics(tmp_path, "B", "S", "A", 9.0, get=fake_get)
    res = ly.get_lyrics(tmp_path, "B", "S", "A", 9.0, get=fake_get, force=True)
    assert len(calls) == 2
    assert res.found is True


def test_network_error_is_not_cached_as_a_miss(tmp_path):
    """An offline device must not permanently mark songs as lyric-less."""
    def boom(url, **kw):
        raise OSError("no route to host")

    res = ly.get_lyrics(tmp_path, "B", "S", "A", 9.0, get=boom)
    assert res.found is False
    assert res.error
    assert not ly.cache_path(tmp_path, "B", "S").exists()


def test_a_corrupt_cache_file_is_ignored(tmp_path):
    ly.cache_path(tmp_path, "B", "S").write_text("{ not json")

    def fake_get(url, **kw):
        return json.dumps({"syncedLyrics": _LRC, "plainLyrics": "",
                           "instrumental": False}).encode()

    assert ly.get_lyrics(tmp_path, "B", "S", "A", 9.0, get=fake_get).found


def test_query_includes_the_track_metadata(tmp_path):
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        return None

    ly.get_lyrics(tmp_path, "Daft Punk", "Instant Crush", "RAM", 337.0,
                  get=fake_get)
    assert "lrclib.net" in seen[0]
    assert "Daft" in seen[0] and "Instant" in seen[0]
    assert "337" in seen[0]


def test_no_request_without_artist_or_title(tmp_path):
    calls = []
    res = ly.get_lyrics(tmp_path, "", "", "", 0.0,
                        get=lambda url, **kw: calls.append(url))
    assert calls == []
    assert res.found is False


# ── Lyricsfile (word timing) ──────────────────────────────────────────────────

_LYRICSFILE = """version: '1.0'
lines:
  - text: 'Stay until the morning'
    start_ms: 4200
    end_ms: 6800
    words:
      - text: 'Stay '
        start_ms: 4200
        end_ms: 4800
      - text: 'until '
        start_ms: 4800
      - text: 'morning'
        start_ms: 5750
  - text: 'Second line'
    start_ms: 7000
"""


def test_lyricsfile_words_get_their_ends_filled_in():
    lines = ly.parse_lyricsfile(_LYRICSFILE)
    assert [(w.text, w.start, w.end) for w in lines[0].words] == [
        ("Stay ", 4.2, 4.8), ("until ", 4.8, 5.75), ("morning", 5.75, 6.8)]
    assert lines[1].words == [] and lines[1].start == 7.0


def test_junk_lyricsfile_falls_back_to_nothing():
    assert ly.parse_lyricsfile("::: not yaml [") == []
    assert ly.parse_lyricsfile("version: '1.0'") == []


def test_a_word_synced_payload_is_word_synced(tmp_path):
    def fake_get(url, **kw):
        return json.dumps({"syncedLyrics": _LRC, "plainLyrics": "",
                           "lyricsfile": _LYRICSFILE}).encode()
    res = ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    assert res.word_synced and res.synced
    assert res.lines[0] == (4.2, "Stay until the morning")   # lyricsfile wins


def test_line_only_lyrics_get_line_ends_from_the_next_line(tmp_path):
    def fake_get(url, **kw):
        return json.dumps({"syncedLyrics": _LRC, "plainLyrics": ""}).encode()
    res = ly.get_lyrics(tmp_path, "Band", "Song", "Album", 90.0, get=fake_get)
    assert not res.word_synced
    assert res.timed[0].end == res.timed[1].start


def test_an_old_cache_entry_is_refetched_once_for_the_lyricsfile(tmp_path):
    path = ly.cache_path(tmp_path, "Band", "Song")
    path.write_text(json.dumps({"synced": _LRC, "plain": "", "instrumental": False}))
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return json.dumps({"syncedLyrics": _LRC, "lyricsfile": _LYRICSFILE}).encode()

    assert ly.get_lyrics(tmp_path, "Band", "Song", "A", 90.0, get=fake_get).word_synced
    ly.get_lyrics(tmp_path, "Band", "Song", "A", 90.0, get=fake_get)
    assert len(calls) == 1                         # upgraded, then cached


def test_offline_upgrade_keeps_the_old_cache(tmp_path):
    path = ly.cache_path(tmp_path, "Band", "Song")
    path.write_text(json.dumps({"synced": _LRC, "plain": "", "instrumental": False}))

    def offline(url, **kw):
        raise OSError("no route")

    res = ly.get_lyrics(tmp_path, "Band", "Song", "A", 90.0, get=offline)
    assert res.found and res.synced and not res.error
