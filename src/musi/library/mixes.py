"""Smart mixes — playlists musi builds for you.

Sources, all optional — a mix that has nothing to say is simply not offered:
  - your play history in musi (play_history),
  - ListenBrainz: the playlists it generates for you (Daily Jams, Weekly
    Jams, Weekly Exploration) and your top songs — public data, so only the
    username is needed, not a token,
  - Navidrome: songs similar to one you pick ("Start radio").

ListenBrainz knows songs by name, not by file, so its tracks are matched to
your library (local files and synced server songs) by artist + title; what
you don't have is skipped. Local copies win over server copies.

Everything here is blocking network/SQL — call it from a worker thread.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

LB_API = "https://api.listenbrainz.org/1"
TIMEOUT_S = 15
MIX_LEN = 50

log = logging.getLogger(__name__)


@dataclass
class Mix:
    key: str
    title: str
    subtitle: str
    tracks: list[dict] = field(default_factory=list)   # path, title, artist, duration
    colours: tuple = ((255, 92, 138), (122, 59, 255))  # card gradient


# ── matching ListenBrainz names to library files ──────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.split(r"\s[\(\[]|\s-\s", s, maxsplit=1)[0]          # "(Remastered)" etc.
    return "".join(ch for ch in s if ch.isalnum())


def _first_artist(s: str) -> str:
    return re.split(r",|&|/|;|\bfeat\.?\b|\bft\.?\b", s or "", flags=re.I)[0]


class Library:
    """Every playable track, indexed by (artist, title) — built once per run."""

    def __init__(self, db) -> None:
        self.by_key: dict[tuple[str, str], dict] = {}
        self.all: list[dict] = []
        rows = db.execute(
            """SELECT t.id, t.path, t.title, t.duration, ar.name AS artist,
                      aa.name AS album_artist
               FROM tracks t
               JOIN artists ar ON ar.id = t.artist_id
               JOIN albums al ON al.id = t.album_id
               JOIN artists aa ON aa.id = al.artist_id""").fetchall()
        for r in rows:
            t = {"id": r["id"], "path": r["path"], "title": r["title"],
                 "artist": r["artist"], "duration": r["duration"] or 0}
            self.all.append(t)
            for a in {r["artist"], r["album_artist"], _first_artist(r["artist"])}:
                key = (_norm(a), _norm(r["title"]))
                old = self.by_key.get(key)
                # local files win over server streams
                if old is None or (old["path"].startswith("http") and not t["path"].startswith("http")):
                    self.by_key[key] = t

    def find(self, artist: str, title: str) -> dict | None:
        for a in (artist, _first_artist(artist)):
            hit = self.by_key.get((_norm(a), _norm(title)))
            if hit:
                return hit
        return None

    def match_all(self, items: list[tuple[str, str]]) -> list[dict]:
        out, seen = [], set()
        for artist, title in items:
            t = self.find(artist, title)
            if t and t["path"] not in seen:
                seen.add(t["path"])
                out.append(t)
        return out


# ── ListenBrainz (public endpoints) ───────────────────────────────────────────

def lb_user() -> str | None:
    """Whose ListenBrainz data to use: the connected token's account, else the
    user name set for mixes on the web page."""
    from musi.library import listenbrainz
    from musi.player import prefs
    s = listenbrainz.load_settings()
    if s and s.get("user") and s["user"] != "?":
        return s["user"]
    return str(prefs.get("listenbrainz_user") or "").strip() or None


def _lb_get(path: str, opener=None):
    url = LB_API + path
    if opener is not None:
        return opener(url)
    req = urllib.request.Request(url, headers={"User-Agent": "musi/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        if resp.status == 204:                    # "no stats yet"
            return None
        return json.loads(resp.read() or b"null")


def lb_generated(user: str, opener=None) -> dict[str, tuple[str, list[tuple[str, str]]]]:
    """Newest generated playlist of each kind → (title, [(artist, title)])."""
    q = urllib.parse.quote(user)
    data = _lb_get(f"/user/{q}/playlists/createdfor?count=25", opener) or {}
    newest: dict[str, dict] = {}
    for item in data.get("playlists") or []:
        pl = item.get("playlist") or {}
        ext = (pl.get("extension") or {}).get("https://musicbrainz.org/doc/jspf#playlist") or {}
        kind = ((ext.get("additional_metadata") or {}).get("algorithm_metadata") or {}) \
            .get("source_patch") or ""
        if kind in ("daily-jams", "weekly-jams", "weekly-exploration") and kind not in newest:
            newest[kind] = pl                      # the API lists newest first
    out = {}
    for kind, pl in newest.items():
        mbid = (pl.get("identifier") or "").rsplit("/", 1)[-1]
        full = (_lb_get(f"/playlist/{mbid}", opener) or {}).get("playlist") or {}
        out[kind] = (pl.get("title", kind),
                     [(t.get("creator", ""), t.get("title", "")) for t in full.get("track") or []])
    return out


def lb_top(user: str, range_: str, opener=None) -> list[tuple[str, str, int]]:
    q = urllib.parse.quote(user)
    data = _lb_get(f"/stats/user/{q}/recordings?range={range_}&count=100", opener) or {}
    return [(r.get("artist_name", ""), r.get("track_name", ""), int(r.get("listen_count") or 0))
            for r in (data.get("payload") or {}).get("recordings") or []]


# ── play history ──────────────────────────────────────────────────────────────

def _history(db, since: float, until: float) -> dict[int, int]:
    """track id → plays in [since, until)."""
    rows = db.execute(
        "SELECT track_id, COUNT(*) AS n FROM play_history WHERE played_at >= ? "
        "AND played_at < ? GROUP BY track_id",
        (int(since), int(until))).fetchall()
    return {r["track_id"]: r["n"] for r in rows}


DAY = 86400


def on_repeat(db, lib: Library, lb_month: list | None, now: float) -> Mix | None:
    counts = dict(_history(db, now - 30 * DAY, now + 1))
    ids = {t["id"]: t for t in lib.all}
    for artist, title, n in lb_month or []:             # ListenBrainz adds the
        t = lib.find(artist, title)                     # plays from elsewhere
        if t:
            counts[t["id"]] = max(counts.get(t["id"], 0), n)
    top = [ids[i] for i, n in sorted(counts.items(), key=lambda kv: -kv[1])
           if n >= 2 and i in ids][:MIX_LEN]
    if len(top) < 5:
        return None
    return Mix("on-repeat", "On Repeat", "Your most played, last 30 days", top,
               ((255, 120, 70), (190, 30, 90)))


def forgotten(db, lib: Library, lb_all: list | None, lb_month: list | None,
              now: float) -> Mix | None:
    recent = _history(db, now - 60 * DAY, now + 1)
    old = _history(db, 0, now - 60 * DAY)
    ids = {t["id"]: t for t in lib.all}
    picks = {i: n for i, n in old.items() if n >= 3 and i not in recent}
    month = {(_norm(a), _norm(t)) for a, t, _ in lb_month or []}
    for artist, title, n in lb_all or []:               # loved once, quiet now
        t = lib.find(artist, title)
        if t and (_norm(artist), _norm(title)) not in month and t["id"] not in recent:
            picks[t["id"]] = max(picks.get(t["id"], 0), n)
    out = [ids[i] for i, _ in sorted(picks.items(), key=lambda kv: -kv[1]) if i in ids][:MIX_LEN]
    if len(out) < 5:
        return None
    return Mix("forgotten", "Forgotten Favourites", "Loved before, not lately", out,
               ((70, 160, 255), (40, 40, 140)))


def daily_mix(db, lib: Library, parts: list[Mix], now: float) -> Mix | None:
    """Favourites, rediscoveries and songs you rarely play — reshuffled once a
    day (seeded by the date, so it holds still until tomorrow)."""
    if len(lib.all) < 20:
        return None
    rng = random.Random(time.strftime("%Y-%m-%d", time.localtime(now)))
    played = _history(db, 0, now + 1)
    pool: list[dict] = []
    for m in parts:
        pool += rng.sample(m.tracks, min(10, len(m.tracks)))
    rare = [t for t in lib.all if played.get(t["id"], 0) <= 1]
    pool += rng.sample(rare, min(MIX_LEN - len(pool), len(rare)))
    seen, out = set(), []
    for t in pool:
        if t["path"] not in seen:
            seen.add(t["path"])
            out.append(t)
    rng.shuffle(out)
    return Mix("daily", "Daily Mix", "Fresh every morning", out[:MIX_LEN],
               ((46, 196, 150), (16, 90, 110)))


_LB_LOOK = {
    "daily-jams":         ("Daily Jams", "From ListenBrainz · today", ((255, 170, 60), (200, 70, 30))),
    "weekly-jams":        ("Weekly Jams", "From ListenBrainz · this week", ((180, 90, 255), (70, 30, 140))),
    "weekly-exploration": ("Weekly Exploration", "New to you · from ListenBrainz", ((60, 200, 220), (20, 80, 140))),
}


def build(db, lb_user: str | None = None, now: float | None = None,
          opener=None) -> list[Mix]:
    """Every mix there's enough data for, in display order."""
    now = time.time() if now is None else now
    lib = Library(db)
    lb_month = lb_all = None
    generated: dict = {}
    if lb_user:
        try:
            lb_month = lb_top(lb_user, "month", opener)
            lb_all = lb_top(lb_user, "all_time", opener)
            generated = lb_generated(lb_user, opener)
        except Exception:
            log.info("mixes: ListenBrainz unreachable", exc_info=True)
    mixes: list[Mix] = []
    rep = on_repeat(db, lib, lb_month, now)
    fav = forgotten(db, lib, lb_all, lb_month, now)
    day = daily_mix(db, lib, [m for m in (rep, fav) if m], now)
    for m in (day, rep, fav):
        if m:
            mixes.append(m)
    for kind in ("daily-jams", "weekly-jams", "weekly-exploration"):
        if kind in generated:
            title, items = generated[kind]
            tracks = lib.match_all(items)
            if len(tracks) >= 3:
                name, sub, cols = _LB_LOOK[kind]
                have = f"{len(tracks)} of {len(items)} in your library"
                mixes.append(Mix(kind, name, f"{sub} · {have}", tracks, cols))
    return mixes


# ── song radio ────────────────────────────────────────────────────────────────

def song_radio(db, seed: dict, client=None) -> Mix:
    """A queue that starts with ``seed`` and continues with similar songs:
    Navidrome's suggestions when it has them, else the same artist and a
    random spread of your library."""
    from musi.library import remote
    lib = Library(db)
    out: list[dict] = [seed]
    if client is not None:
        try:
            sid = remote.song_id(seed["path"])
            if sid is None:                          # a local file: find it on the server
                hits = client.search_songs(f"{seed.get('artist', '')} {seed.get('title', '')}", 5)
                sid = next((h["id"] for h in hits
                            if _norm(h.get("title", "")) == _norm(seed.get("title", ""))), None)
            for s in client.similar_songs(sid, MIX_LEN) if sid else []:
                t = lib.find(s.get("artist", ""), s.get("title", ""))
                if t is None:                        # not synced yet: stream it anyway
                    t = {"path": remote.stream_url(str(s["id"])), "title": s.get("title", ""),
                         "artist": s.get("artist", ""), "duration": s.get("duration") or 0}
                out.append(t)
        except Exception:
            log.info("mixes: Navidrome similar songs failed", exc_info=True)
    if len(out) < 10:                                # fallback: same artist, then anything
        rng = random.Random()
        same = [t for t in lib.all if _norm(t["artist"]) == _norm(seed.get("artist", ""))]
        rng.shuffle(same)
        rest = list(lib.all)
        rng.shuffle(rest)
        out += same[:15] + rest[:MIX_LEN]
    seen, uniq = set(), []
    for t in out:
        if t["path"] and t["path"] not in seen:
            seen.add(t["path"])
            uniq.append(t)
    return Mix("radio", f"{seed.get('title', 'Song')} Radio", "Songs like this one",
               uniq[:MIX_LEN])


# ── background refresh (the Music home shows whatever is ready) ───────────────

REFRESH_S = 30 * 60

_ready: list[Mix] = []
_built_at = 0.0
_building = False
_version = 0          # bumps when a new set lands, so screens know to redraw


def ready() -> tuple[int, list[Mix]]:
    return _version, list(_ready)


def refresh_async(db_path, force: bool = False) -> bool:
    """Rebuild the mixes on a thread if they're stale. Returns True if a
    build started. Uses its own database connection."""
    global _building
    import threading
    if _building or (not force and time.time() - _built_at < REFRESH_S):
        return False
    _building = True

    def work() -> None:
        global _ready, _built_at, _building, _version
        conn = None
        try:
            from musi.library.db import open_db
            conn = open_db(db_path)
            _ready = build(conn, lb_user())
            _built_at = time.time()
            _version += 1
        except Exception:
            log.warning("mixes: build failed", exc_info=True)
        finally:
            if conn is not None:
                conn.close()
            _building = False

    threading.Thread(target=work, daemon=True).start()
    return True
