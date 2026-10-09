"""NetEase Cloud Music lyrics — the second source, for word-by-word timing.

Unofficial (the public web API many open-source lyric apps use), so it is
only ever an extra: library/lyrics.py asks LRCLIB first and comes here when
LRCLIB has no word timing, or nothing at all. Every failure here returns
None and the LRCLIB answer stands.

Matching is strict — a wrong version is worse than no word timing: the title
must match (ignoring "(… Remix)"-style suffixes only when the length also
matches), one artist must match, and the length must be within 3 seconds
when we know ours.

Two lyric formats come back:
  lrc  — ordinary LRC, line-timed
  yrc  — word-timed: "[line_ms,dur_ms](word_ms,dur_ms,0)word(…)word…"
Both may carry credit lines (JSON objects, or "作词 : …" style) — dropped.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request

SEARCH = "https://music.163.com/api/search/get"
LYRIC  = "https://music.163.com/api/song/lyric/v1"
UA = "Mozilla/5.0 (X11; Linux armv7l) musi/1.0"
TIMEOUT_S = 12
MAX_DURATION_DIFF_S = 3.0
MAX_TRIES = 3            # copies of the same song whose lyrics we'll fetch

# versions that share the title and length but are not the sung track
_NOT_VOCAL = re.compile(r"instrumental|karaoke|伴奏|off ?vocal|backing track", re.I)

_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD = re.compile(r"\((\d+),(\d+),\d+\)([^(]*)")
# Chinese credit lines: 作词 lyrics, 作曲 music, 编曲 arrangement, 制作人 producer…
_CREDIT = re.compile(r"^\s*(作词|作曲|编曲|制作人?|混音|母带|和声|吉他|贝斯|鼓|录音|监制|"
                     r"出品|企划|统筹|演唱|原唱|翻唱|词|曲)\s*[:：]")

log = logging.getLogger(__name__)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://music.163.com/"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read(2 * 1024 * 1024)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return "".join(ch for ch in s if ch.isalnum())


def _base_title(s: str) -> str:
    """'Unicorn (Hope Version)' / 'Song - 2011 Remaster' → 'unicorn' / 'song'."""
    s = re.split(r"\s[\(\[]|\s-\s", s or "", maxsplit=1)[0]
    return _norm(s)


def _artists(s: str) -> set[str]:
    parts = re.split(r",|&|/|;|\bfeat\.?\b|\bft\.?\b|\bx\b", s or "", flags=re.I)
    return {_norm(p) for p in parts if _norm(p)}


def matches(songs: list[dict], title: str, artist: str, duration: float) -> list[dict]:
    """Search results that really are this track, best first.

    NetEase often lists one recording several times (re-uploads, regional
    releases), and only some copies carry word timing — so every copy that
    passes is returned, exact titles before 'same base title', then by how
    close the length is.
    """
    want_title, want_base, want_artists = _norm(title), _base_title(title), _artists(artist)
    ranked = []
    for s in songs:
        name = s.get("name", "")
        if _NOT_VOCAL.search(name) and not _NOT_VOCAL.search(title):
            continue
        names = {_norm(a.get("name", "")) for a in s.get("artists") or []}
        if not (names & want_artists):
            continue
        exact = _norm(name) == want_title
        cand_dur = (s.get("duration") or 0) / 1000
        if duration > 0 and cand_dur > 0:
            diff = abs(cand_dur - duration)
            if diff > MAX_DURATION_DIFF_S or not (exact or _base_title(name) == want_base):
                continue
        elif not exact:
            continue                                  # no length to check: exact only
        else:
            diff = 0.0
        ranked.append((not exact, diff, s))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [s for _, _, s in ranked]


def best_match(songs: list[dict], title: str, artist: str, duration: float) -> dict | None:
    found = matches(songs, title, artist, duration)
    return found[0] if found else None


def parse_yrc(text: str) -> list[tuple[float, float, list[tuple[float, float, str]]]]:
    """[(line_start, line_end, [(word_start, word_end, word_text)])] in seconds.

    Whitespace-only tokens (yrc puts trailing spaces in their own slots) are
    folded into the word before them, so each word carries its space.
    """
    out = []
    for raw in (text or "").splitlines():
        m = _YRC_LINE.match(raw.strip())
        if not m:
            continue                                    # credits are JSON lines
        start, dur = int(m.group(1)) / 1000, int(m.group(2)) / 1000
        words: list[tuple[float, float, str]] = []
        for wm in _YRC_WORD.finditer(m.group(3)):
            ws, wd, wt = int(wm.group(1)) / 1000, int(wm.group(2)) / 1000, wm.group(3)
            if not wt.strip():
                if words:
                    s0, e0, t0 = words[-1]
                    words[-1] = (s0, e0, t0 + wt)
                continue
            words.append((ws, ws + wd, wt))
        text_line = "".join(w[2] for w in words).strip()
        if not words or _CREDIT.match(text_line):
            continue
        out.append((start, start + dur, words))
    return out


def clean_lrc(text: str) -> str:
    """NetEase LRC minus its JSON / credit lines."""
    keep = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if s.startswith("{"):
            continue
        body = re.sub(r"^(\[[^\]]*\])+", "", s)
        if _CREDIT.match(body):
            continue
        keep.append(raw)
    return "\n".join(keep)


def fetch(title: str, artist: str, duration: float, get=_get) -> dict | None:
    """{"id", "yrc", "lrc"} for this track, or None (no confident match).

    Raises on transport errors so the caller can tell 'not there' (cache it)
    from 'couldn't ask' (try again next time).
    """
    q = urllib.parse.urlencode({"s": f"{title} {artist}", "type": 1, "limit": 10})
    try:
        data = json.loads(get(f"{SEARCH}?{q}"))
    except ValueError:
        return None
    songs = ((data or {}).get("result") or {}).get("songs") or []
    line_only = None
    for song in matches(songs, title, artist, duration)[:MAX_TRIES]:
        q = urllib.parse.urlencode({"id": song["id"], "lv": 1, "yv": 1, "tv": 0})
        try:
            lyr = json.loads(get(f"{LYRIC}?{q}"))
        except ValueError:
            continue
        yrc = ((lyr or {}).get("yrc") or {}).get("lyric") or ""
        lrc = clean_lrc(((lyr or {}).get("lrc") or {}).get("lyric") or "")
        if yrc and parse_yrc(yrc):
            return {"id": song["id"], "yrc": yrc, "lrc": lrc}
        if lrc.strip() and line_only is None:
            line_only = {"id": song["id"], "yrc": "", "lrc": lrc}
    return line_only
