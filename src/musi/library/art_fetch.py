"""Fetch missing album art from the Cover Art Archive.

Two hops, both free and keyless:

  1. MusicBrainz  — search release-groups for "artist + album", take the top hit
  2. Cover Art Archive — GET the front image for that release-group MBID

Only albums with no *local* source (no embedded art, no cover.jpg beside the
audio) are candidates — see art.has_local_source. Results go through
art.override_art, so a fetched cover survives later rescans exactly like a
user-uploaded one.

Never runs on its own: the Settings → Artwork screen drives it, so a Zero W
mid-playback is never surprised by network and image work.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from musi.library.art import album_slug, has_local_source, override_art

_MB_URL  = "https://musicbrainz.org/ws/2/release-group/"
_CAA_URL = "https://coverartarchive.org/release-group/{mbid}/front-500"

# MusicBrainz rejects requests without a descriptive User-Agent.
_UA = "musi/1.0 (https://github.com/il-web/musi)"

# MusicBrainz asks for no more than one request per second.
_PAUSE_S = 1.0

# Generous: the Zero W's WiFi plus a cold TLS handshake to MusicBrainz, and the
# Cover Art Archive redirecting to archive.org, both take real time. A timeout
# only skips that album — no marker is written, so the next run retries it.
_TIMEOUT = 25.0


def _http_get(url: str, *, accept_image: bool = False,
              timeout: float = _TIMEOUT) -> bytes | None:
    """GET url, returning the body, or None on any 4xx/5xx or transport error."""
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "image/*" if accept_image else "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        logging.info("art_fetch: GET failed for %s", url, exc_info=True)
        return None


# ── discovery ─────────────────────────────────────────────────────────────────

def fetched_marker(art_dir: Path, album_key: str) -> Path:
    """Sidecar recording that this album's art already came from the archive.

    The cache files a fetch writes look exactly like locally-sourced art, so
    without this every run would re-download everything and hammer MusicBrainz.
    """
    return art_dir / f"{album_slug(album_key)}.fetched"


def albums_missing_art(conn: sqlite3.Connection,
                       art_dir: Path | None = None) -> list[dict]:
    """Albums whose tracks carry no artwork locally, in display order.

    Albums already covered by a previous fetch are excluded when art_dir is
    given. Reads one audio file per album, so this is disk work — call it off
    the render loop.
    """
    rows = conn.execute(
        """SELECT al.id, al.title AS album, ar.name AS artist,
                  MIN(t.path) AS probe
           FROM albums al
           JOIN artists ar ON ar.id = al.artist_id
           JOIN tracks  t  ON t.album_id = al.id
           GROUP BY al.id
           ORDER BY ar.name COLLATE NOCASE, al.title COLLATE NOCASE"""
    ).fetchall()

    missing = []
    for r in rows:
        # must match scanner._album_key so the slug addresses the same files
        album_key = f"{r['artist']}::{r['album']}"
        if art_dir is not None and fetched_marker(art_dir, album_key).exists():
            continue
        probe = Path(r["probe"])
        try:
            if has_local_source(probe):
                continue
        except Exception:
            logging.info("art_fetch: unreadable probe %s", probe, exc_info=True)
        missing.append({
            "id":        r["id"],
            "artist":    r["artist"],
            "album":     r["album"],
            "album_key": album_key,
        })
    return missing


# ── lookup ────────────────────────────────────────────────────────────────────

def _lucene_escape(text: str) -> str:
    """Escape the Lucene metacharacters MusicBrainz would otherwise parse."""
    out = []
    for ch in text:
        if ch in '\\+-&|!(){}[]^"~*?:/':
            out.append("\\")
        out.append(ch)
    return "".join(out)


def find_cover(artist: str, album: str, *,
               get: Callable[..., bytes | None] = _http_get,
               timeout: float = _TIMEOUT) -> bytes | None:
    """Front cover bytes for artist+album, or None if nothing matches."""
    query = (f'artist:"{_lucene_escape(artist)}" '
             f'AND releasegroup:"{_lucene_escape(album)}"')
    url = _MB_URL + "?" + urllib.parse.urlencode(
        {"query": query, "fmt": "json", "limit": 1})

    try:
        body = get(url, timeout=timeout)
        if not body:
            return None
        groups = json.loads(body).get("release-groups") or []
        if not groups:
            return None
        mbid = groups[0].get("id")
        if not mbid:
            return None
        return get(_CAA_URL.format(mbid=mbid), accept_image=True,
                   timeout=timeout) or None
    except Exception:
        logging.info("art_fetch: lookup failed for %s / %s", artist, album,
                     exc_info=True)
        return None


# ── run ───────────────────────────────────────────────────────────────────────

def fetch_missing(conn: sqlite3.Connection, art_dir: Path, *,
                  get: Callable[..., bytes | None] = _http_get,
                  pause: float = _PAUSE_S,
                  progress: Callable[[int, int, str], None] | None = None,
                  should_stop: Callable[[], bool] | None = None,
                  ) -> tuple[int, int]:
    """Fetch art for every album missing it. Returns (found, considered).

    Blocking and slow by design — one album per second at best. Run it on a
    worker thread and poll `progress`.
    """
    todo = albums_missing_art(conn, art_dir)
    total = len(todo)
    found = 0

    for i, item in enumerate(todo):
        if should_stop is not None and should_stop():
            break
        if progress is not None:
            progress(i, total, f"{item['artist']} — {item['album']}")

        data = find_cover(item["artist"], item["album"], get=get)
        if data:
            try:
                thumb, backdrop, palette = override_art(
                    data, art_dir, item["album_key"])
                conn.execute(
                    "UPDATE albums SET art_path = ?, backdrop_path = ?,"
                    " palette = ? WHERE id = ?",
                    (str(thumb), str(backdrop), json.dumps(palette), item["id"]))
                conn.commit()
                fetched_marker(art_dir, item["album_key"]).touch()
                found += 1
            except Exception:
                logging.warning("art_fetch: could not store art for %s",
                                item["album_key"], exc_info=True)
        if pause:
            time.sleep(pause)

    if progress is not None:
        progress(total, total, "Done")
    return found, total
