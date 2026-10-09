"""NetEase — the second lyrics source, for word-by-word timing.

No network: canned search/lyric replies shaped like the real ones.
"""
import json
import urllib.parse

import pytest

from musi.library import lyrics as ly
from musi.library import netease as ne

YRC = "\n".join([
    '{"t":0,"c":[{"tx":"作曲: "},{"tx":"Someone"}]}',
    "[18570,1950](18570,210,0)I (18780,420,0)come (19200,180,0)and (19380,90,0)I "
    "(19470,1020,0)go(20490,30,0) ",
    "[20520,2190](20520,360,0)Don(20880,40,0)’(20920,260,0)t (21180,300,0)go",
])
LRC = "\n".join([
    '{"t":0,"c":[{"tx":"作曲: "}]}',
    "[00:00.00] 作词 : Someone",
    "[00:18.57] I come and I go",
    "[00:20.52] Don’t go",
])


def _song(id_, name, dur_s, artists=("Dua Lipa",)):
    return {"id": id_, "name": name, "duration": int(dur_s * 1000),
            "artists": [{"name": a} for a in artists]}


SONGS = [
    _song(1, "Houdini (Live from the Royal Albert Hall)", 216.5),
    _song(2, "Houdini", 185.9),                    # line-timed copy
    _song(3, "Houdini (Instrumental)", 185.9),     # same length — must never match
    _song(4, "Houdini", 185.9),                    # word-timed copy
    _song(5, "Houdini", 185.9, artists=("Someone Else",)),
]


class FakeNetEase:
    def __init__(self, lyrics_by_id=None, down=False):
        self.lyrics_by_id = lyrics_by_id or {2: {"lrc": LRC}, 4: {"lrc": LRC, "yrc": YRC}}
        self.down, self.urls = down, []

    def __call__(self, url, **kw):
        self.urls.append(url)
        if self.down:
            raise OSError("no route")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        if "/search/" in url:
            return json.dumps({"result": {"songs": SONGS}}).encode()
        got = self.lyrics_by_id.get(int(q["id"]), {})
        return json.dumps({k: {"lyric": v} for k, v in got.items()}).encode()


# ── matching ──────────────────────────────────────────────────────────────────

def test_only_the_same_recording_matches():
    ids = [s["id"] for s in ne.matches(SONGS, "Houdini", "Dua Lipa", 185.0)]
    assert ids == [2, 4]                 # live: wrong length; instrumental; other artist


def test_without_a_length_only_an_exact_title_matches():
    songs = [_song(9, "Houdini (Extended)", 353.8), _song(10, "Houdini", 185.9)]
    assert [s["id"] for s in ne.matches(songs, "Houdini", "Dua Lipa", 0)] == [10]


def test_a_feat_artist_list_still_matches():
    songs = [_song(7, "Song", 200, artists=("A", "B"))]
    assert ne.matches(songs, "Song", "B feat. C", 200)


# ── parsing ───────────────────────────────────────────────────────────────────

def test_yrc_words_carry_their_spaces_and_credits_are_dropped():
    lines = ne.parse_yrc(YRC)
    assert len(lines) == 2
    start, end, words = lines[0]
    assert (start, round(end, 2)) == (18.57, 20.52)
    assert [w[2] for w in words] == ["I ", "come ", "and ", "I ", "go"]   # line end: no space needed
    assert [w[2] for w in lines[1][2]] == ["Don", "’", "t ", "go"]


def test_netease_lrc_loses_its_credit_lines():
    assert ly.parse_lrc(ne.clean_lrc(LRC)) == [(18.57, "I come and I go"),
                                              (20.52, "Don’t go")]


def test_fetch_keeps_looking_past_a_line_only_copy():
    got = ne.fetch("Houdini", "Dua Lipa", 185.0, get=FakeNetEase())
    assert got["id"] == 4 and got["yrc"]


def test_fetch_settles_for_lines_when_no_copy_has_words():
    got = ne.fetch("Houdini", "Dua Lipa", 185.0, get=FakeNetEase({2: {"lrc": LRC}}))
    assert got["id"] == 2 and not got["yrc"] and got["lrc"]


def test_no_confident_match_is_none():
    assert ne.fetch("Houdini", "Dua Lipa", 300.0, get=FakeNetEase()) is None


# ── how it joins LRCLIB ───────────────────────────────────────────────────────

def _lrclib(synced="", lyricsfile="", instrumental=False):
    def get(url, **kw):
        return json.dumps({"syncedLyrics": synced, "plainLyrics": "",
                           "lyricsfile": lyricsfile, "instrumental": instrumental}).encode()
    return get


def test_netease_words_beat_lrclib_lines(tmp_path):
    res = ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0,
                        get=_lrclib(synced="[00:18.57] I come and I go"),
                        netease_get=FakeNetEase())
    assert res.word_synced and res.source == "NetEase"
    assert res.timed[0].text == "♪"                 # 18 s intro becomes dots


def test_netease_is_not_asked_when_lrclib_has_words(tmp_path):
    lf = ("version: '1.0'\nlines:\n  - text: 'Hi'\n    start_ms: 0\n    end_ms: 900\n"
          "    words:\n      - text: 'Hi'\n        start_ms: 0\n")
    net = FakeNetEase()
    res = ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0,
                        get=_lrclib(lyricsfile=lf), netease_get=net)
    assert res.source == "LRCLIB" and res.word_synced and net.urls == []


def test_netease_lines_fill_in_when_lrclib_has_nothing(tmp_path):
    res = ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0,
                        get=lambda url, **kw: None,                 # LRCLIB 404
                        netease_get=FakeNetEase({2: {"lrc": LRC}}))
    assert res.found and res.synced and res.source == "NetEase"
    assert not res.word_synced


def test_instrumentals_never_ask_netease(tmp_path):
    net = FakeNetEase()
    ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0,
                  get=_lrclib(instrumental=True), netease_get=net)
    assert net.urls == []


def test_netease_down_is_retried_next_time_but_no_match_is_not(tmp_path):
    get = _lrclib(synced="[00:18.57] I come and I go")
    down = FakeNetEase(down=True)
    first = ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0, get=get, netease_get=down)
    assert first.synced and not first.word_synced    # LRCLIB still shows
    up = FakeNetEase()
    again = ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0, get=get, netease_get=up)
    assert again.word_synced                         # asked again, from cache
    third = FakeNetEase()
    ly.get_lyrics(tmp_path, "Dua Lipa", "Houdini", "", 185.0, get=get, netease_get=third)
    assert third.urls == []                          # answered: never asked again
