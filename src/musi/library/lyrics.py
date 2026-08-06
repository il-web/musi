"""Synced lyrics from LRCLIB, cached on disk.

LRCLIB is keyless and returns LRC-format synced lyrics plus a plain-text
fallback. Nothing here runs on its own: the Now Playing lyrics button asks for
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
class Lyrics:
    """Resolved lyrics for one track."""
    lines: list[tuple[float, str]] = field(default_factory=list)  # synced
    plain: str = ""
    synced: bool = False
    found: bool = False
    instrumental: bool = False
    error: str = ""


def _http_get(url: str, *, timeout: float = _TIMEOUT) -> bytes | None:
    """GET url. Returns None on a 404 (a real 'no lyrics'); raises otherwise."""
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
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
    synced = parse_lrc(payload.get("synced") or "")
    plain  = payload.get("plain") or ""
    return Lyrics(
        lines        = synced,
        plain        = plain,
        synced       = bool(synced),
        found        = bool(synced or plain),
        instrumental = bool(payload.get("instrumental")),
    )


# ── fetch ─────────────────────────────────────────────────────────────────────

def get_lyrics(lyrics_dir: Path, artist: str, title: str, album: str,
               duration: float, *,
               get: Callable[..., bytes | None] = _http_get,
               force: bool = False) -> Lyrics:
    """Cached lyrics for one track, fetching from LRCLIB on a miss.

    Blocking — call it on a worker thread.
    """
    if not artist or not title:
        return Lyrics(error="Track has no artist or title")

    path = cache_path(lyrics_dir, artist, title)
    if not force and path.exists():
        try:
            return _from_payload(json.loads(path.read_text(encoding="utf-8")))
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
        return Lyrics(error=str(exc) or "network error")

    payload = {"synced": "", "plain": "", "instrumental": False}
    if body:
        try:
            data = json.loads(body)
            payload = {
                "synced":       data.get("syncedLyrics") or "",
                "plain":        data.get("plainLyrics") or "",
                "instrumental": bool(data.get("instrumental")),
            }
        except Exception:
            logging.info("lyrics: unreadable response for %s / %s",
                         artist, title, exc_info=True)
            return Lyrics(error="bad response")

    try:
        Path(lyrics_dir).mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logging.info("lyrics: could not write cache %s", path, exc_info=True)

    return _from_payload(payload)
