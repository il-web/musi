"""Synced lyrics from LRCLIB, cached on disk.

LRCLIB is keyless and returns LRC-format synced lyrics plus a plain-text
fallback — and, newer, a "Lyricsfile" (YAML, https://lrclib.net/lyricsfile)
with each line's start/end and, where someone has timed them, every word's.
Word timing is used when present; otherwise lines are timed from the LRC.

NetEase (library/netease.py, unofficial) is the second source: asked only
when LRCLIB has no word timing, it adds word timing where it has a confident
match — or line-timed lyrics when LRCLIB has none at all. Nothing here runs on its own: the Now Playing lyrics button asks for
the current track only, and the answer is cached forever, so a song costs one
request in its lifetime.

Misses are cached too (an offline Zero W should not re-query on every open),
but only *negative answers from the server* — a transport failure is never
written, or going offline once would mark songs lyric-less permanently. Passing
force=True retries a cached miss.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_API = "https://lrclib.net/api/get"
_UA  = "musi/1.0 (https://github.com/il-web/musi)"
_TIMEOUT = 20.0

# [mm:ss.xx] or [mm:ss] — repeated tags on one line mean a repeated lyric.
_TAG  = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_META = re.compile(r"^\[[a-zA-Z]+:")


@dataclass
class Word:
    start: float            # seconds
    end: float              # seconds (next word's start if the file omits it)
    text: str               # includes its trailing space, as in the file


@dataclass
class Line:
    start: float
    end: float              # next line's start when the source has no end
    text: str
    words: list[Word] = field(default_factory=list)   # empty = line-timed only


@dataclass
class Lyrics:
    """Resolved lyrics for one track."""
    lines: list[tuple[float, str]] = field(default_factory=list)  # synced
    plain: str = ""
    synced: bool = False
    found: bool = False
    instrumental: bool = False
    error: str = ""
    timed: list[Line] = field(default_factory=list)   # lines with end + words
    word_synced: bool = False
    source: str = "LRCLIB"                             # whose timing is shown


# Cache payload format. v2 added the Lyricsfile, v3 the NetEase answer; an
# older entry is re-fetched once (served from the old cache if that fails).
CACHE_VERSION = 3
BREAK_S = 6.0           # a silence this long becomes a "• • •" line


# A synced lyric file is a few KB. Cap the read so a hostile or broken endpoint
# can't stream the 512MB Zero W out of memory.
_MAX_BYTES = 2 * 1024 * 1024


def _http_get(url: str, *, timeout: float = _TIMEOUT) -> bytes | None:
    """GET url. Returns None on a 404 (a real 'no lyrics'); raises otherwise."""
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(_MAX_BYTES + 1)
            if len(body) > _MAX_BYTES:
                raise ValueError(f"lyrics response over {_MAX_BYTES} bytes")
            return body
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None                      # definitive: LRCLIB has nothing
        raise


# ── LRC parsing ───────────────────────────────────────────────────────────────

def parse_lrc(text: str) -> list[tuple[float, str]]:
    """[(seconds, text)] sorted by time. Metadata tags are dropped."""
    out: list[tuple[float, str]] = []
    for raw in (text or "").splitlines():
        tags = list(_TAG.finditer(raw))
        if not tags:
            continue
        if _META.match(raw) and not tags:
            continue
        body = raw[tags[-1].end():].strip()
        for m in tags:
            mins, secs, frac = m.group(1), m.group(2), m.group(3) or "0"
            # LRC fractions are hundredths; pad so "3" reads as .30, not .03
            t = int(mins) * 60 + int(secs) + int(frac.ljust(2, "0")[:2]) / 100
            out.append((t, body))
    out.sort(key=lambda p: p[0])
    return out


def parse_lyricsfile(text: str) -> list[Line]:
    """Lines (with word timing where present) from a Lyricsfile, or [] if it
    can't be read — the caller then falls back to the LRC."""
    if not text:
        return []
    try:
        import yaml
        doc = yaml.safe_load(text)
    except Exception:                       # no PyYAML, or not valid YAML
        return []
    raw = doc.get("lines") if isinstance(doc, dict) else None
    out: list[Line] = []
    for ln in raw or []:
        if not isinstance(ln, dict) or not isinstance(ln.get("start_ms"), (int, float)):
            continue
        words = [Word(w["start_ms"] / 1000,
                      (w["end_ms"] / 1000) if isinstance(w.get("end_ms"), (int, float)) else -1.0,
                      str(w.get("text", "")))
                 for w in ln.get("words") or []
                 if isinstance(w, dict) and isinstance(w.get("start_ms"), (int, float))]
        words.sort(key=lambda w: w.start)
        end = ln["end_ms"] / 1000 if isinstance(ln.get("end_ms"), (int, float)) else -1.0
        out.append(Line(ln["start_ms"] / 1000, end, str(ln.get("text", "")), words))
    out.sort(key=lambda l: l.start)
    for i, line in enumerate(out):
        if line.end < 0:
            line.end = out[i + 1].start if i + 1 < len(out) else line.start + 5.0
        for j, w in enumerate(line.words):
            if w.end < 0:
                w.end = line.words[j + 1].start if j + 1 < len(line.words) else line.end
    return out


def timed_from_lrc(lines: list[tuple[float, str]]) -> list[Line]:
    """Line-timed only: each line lasts until the next starts."""
    out = []
    for i, (t, text) in enumerate(lines):
        end = lines[i + 1][0] if i + 1 < len(lines) else t + 5.0
        out.append(Line(t, end, text))
    return out


def timed_from_yrc(text: str) -> list[Line]:
    from musi.library import netease
    return [Line(start, end, "".join(w[2] for w in words).strip(),
                 [Word(ws, we, wt) for ws, we, wt in words])
            for start, end, words in netease.parse_yrc(text)]


def with_breaks(timed: list[Line]) -> list[Line]:
    """Insert a break line ("♪") into long silences — before the first line
    and between lines — so the screen can show its dots there, as Apple does."""
    out: list[Line] = []
    prev_end = 0.0
    for line in timed:
        if line.start - prev_end >= BREAK_S and line.text.strip() != "♪":
            out.append(Line(prev_end, line.start, "♪"))
        out.append(line)
        prev_end = max(prev_end, line.end)
    return out


def active_index(lines: list[tuple[float, str]], elapsed: float) -> int:
    """Index of the line playing at `elapsed`, or -1 before the first."""
    if not lines:
        return -1
    return bisect_right([t for t, _ in lines], elapsed) - 1


# ── cache ─────────────────────────────────────────────────────────────────────

def cache_path(lyrics_dir: Path, artist: str, title: str) -> Path:
    """Stable per-track cache file. Case- and padding-insensitive."""
    key = f"{(artist or '').strip().lower()}::{(title or '').strip().lower()}"
    return Path(lyrics_dir) / f"{hashlib.md5(key.encode()).hexdigest()[:16]}.json"


def _from_payload(payload: dict) -> Lyrics:
    """Pick the best timing on offer, in this order: LRCLIB words, NetEase
    words, LRCLIB lines (Lyricsfile, then LRC), NetEase lines."""
    plain = payload.get("plain") or ""
    ne    = payload.get("netease") or {}
    lf    = parse_lyricsfile(payload.get("lyricsfile") or "")
    lrc   = timed_from_lrc(parse_lrc(payload.get("synced") or ""))
    yrc   = timed_from_yrc(ne.get("yrc") or "")
    source = "LRCLIB"
    if any(l.words for l in lf):
        timed = lf
    elif yrc:
        timed, source = yrc, "NetEase"
    elif lf or lrc:
        timed = lf or lrc
    else:
        timed = timed_from_lrc(parse_lrc(ne.get("lrc") or ""))
        source = "NetEase" if timed else "LRCLIB"
    if any(l.words for l in timed):
        timed = with_breaks(timed)          # exact ends: silences are real
    lines = [(l.start, l.text) for l in timed]
    return Lyrics(
        lines        = lines,
        plain        = plain,
        synced       = bool(lines),
        found        = bool(lines or plain),
        instrumental = bool(payload.get("instrumental")) and not lines,
        timed        = timed,
        word_synced  = any(l.words for l in timed),
        source       = source,
    )


def _wants_netease(payload: dict) -> bool:
    """Worth asking NetEase: LRCLIB has no word timing, the song isn't an
    instrumental, and NetEase hasn't answered for it yet."""
    if (payload.get("netease") or {}).get("checked"):
        return False
    if payload.get("instrumental"):
        return False
    return not any(l.words for l in parse_lyricsfile(payload.get("lyricsfile") or ""))


def _ask_netease(payload: dict, artist: str, title: str, duration: float, get) -> None:
    """Add NetEase's answer to ``payload`` in place. A transport failure
    leaves it unchecked, so the next open tries again; 'no match' is final."""
    from musi.library import netease
    try:
        found = netease.fetch(title, artist, duration, get=get)
    except Exception:
        logging.info("lyrics: NetEase unreachable for %s / %s", artist, title,
                     exc_info=True)
        payload["netease"] = {"checked": False}
        return
    payload["netease"] = {"checked": True,
                          "yrc": (found or {}).get("yrc", ""),
                          "lrc": (found or {}).get("lrc", "")}


# ── fetch ─────────────────────────────────────────────────────────────────────

def get_lyrics(lyrics_dir: Path, artist: str, title: str, album: str,
               duration: float, *,
               get: Callable[..., bytes | None] = _http_get,
               netease_get: Callable[..., bytes] | None = None,
               force: bool = False) -> Lyrics:
    """Cached lyrics for one track, fetching from LRCLIB on a miss.

    Blocking — call it on a worker thread.
    """
    if not artist or not title:
        return Lyrics(error="Track has no artist or title")
    if netease_get is None and get is _http_get:
        # the real LRCLIB getter brings the real NetEase one; a test that
        # injects only an LRCLIB fake leaves NetEase out entirely
        from musi.library import netease
        netease_get = netease._get

    path = cache_path(lyrics_dir, artist, title)
    stale: dict | None = None
    if not force and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("v") == CACHE_VERSION:
                if netease_get and _wants_netease(cached):   # NetEase was down
                    _ask_netease(cached, artist, title, duration, netease_get)
                    if cached["netease"].get("checked"):
                        _write_cache(lyrics_dir, path, cached)
                return _from_payload(cached)
            stale = cached          # pre-Lyricsfile entry: refetch once
        except Exception:
            logging.info("lyrics: ignoring corrupt cache %s", path, exc_info=True)

    query = urllib.parse.urlencode({
        "artist_name": artist,
        "track_name":  title,
        "album_name":  album or "",
        "duration":    int(duration or 0),
    })

    try:
        body = get(f"{_API}?{query}")
    except Exception as exc:
        # transport failure — never cached, or one offline moment would mark
        # the song lyric-less for good
        logging.info("lyrics: fetch failed for %s / %s", artist, title,
                     exc_info=True)
        if stale is not None:
            return _from_payload(stale)     # offline: the old cache will do
        return Lyrics(error=str(exc) or "network error")

    payload = {"v": CACHE_VERSION, "synced": "", "plain": "", "instrumental": False}
    if body:
        try:
            data = json.loads(body)
            payload = {
                "v":            CACHE_VERSION,
                "synced":       data.get("syncedLyrics") or "",
                "plain":        data.get("plainLyrics") or "",
                "instrumental": bool(data.get("instrumental")),
                "lyricsfile":   data.get("lyricsfile") or "",
            }
        except Exception:
            logging.info("lyrics: unreadable response for %s / %s",
                         artist, title, exc_info=True)
            return Lyrics(error="bad response")

    if netease_get and _wants_netease(payload):
        _ask_netease(payload, artist, title, duration, netease_get)
    _write_cache(lyrics_dir, path, payload)
    return _from_payload(payload)


def _write_cache(lyrics_dir: Path, path: Path, payload: dict) -> None:
    try:
        Path(lyrics_dir).mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logging.info("lyrics: could not write cache %s", path, exc_info=True)
