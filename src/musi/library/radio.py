"""Internet radio — finding stations, saving them, turning them into streams.

Two directories:
  - TuneIn, through its public OPML service (opml.radiotime.com) — the one
    Home Assistant and Mopidy-TuneIn use. Best catalog: logos, a "local
    radio" list by location, good search. Not an official partner API, so
    it can change without notice — hence:
  - Radio Browser (radio-browser.info), the open community directory, as
    the automatic fallback when TuneIn errors out.

A station is a plain dict, the same shape whichever directory it came from:

    {"provider": "tunein" | "rb", "id": "s68320", "name": "GLGLZ",
     "subtext": "Music is GLGLZ", "image": "<logo url>", "url": "<stream>"}

``url`` is the last stream address that worked. TuneIn stations are re-tuned
at every play (their stream addresses move); the saved one is the fallback.

Radio streams play through MPD like any URL. They never enter the library
tables, never count as listens, and are told apart from music-server streams
by remote.kind().
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from musi.library import config

TUNEIN = "https://opml.radiotime.com"
RADIO_BROWSER = "https://all.api.radio-browser.info/json"
TIMEOUT_S = 12
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])     # a PNG file starts with these
SEARCH_LIMIT = 40

log = logging.getLogger(__name__)


class RadioError(Exception):
    pass


def _get(url: str, opener=None) -> bytes:
    if opener is not None:
        return opener(url)
    req = urllib.request.Request(url, headers={"User-Agent": "musi/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise RadioError(f"can't reach the radio directory ({getattr(exc, 'reason', exc)})") from exc


def _json(url: str, opener=None):
    try:
        return json.loads(_get(url, opener))
    except ValueError as exc:
        raise RadioError("unexpected reply from the radio directory") from exc


# ── TuneIn ────────────────────────────────────────────────────────────────────

def _tunein_station(e: dict) -> dict | None:
    """One OPML outline → a station, or None for shows/podcasts/links."""
    if e.get("type") != "audio" or e.get("item") != "station" or not e.get("guide_id"):
        return None
    image = e.get("image") or ""
    # logoq (145 px) is what listings send; logod is the 300 px one
    image = image.replace("/logoq.", "/logod.")
    return {"provider": "tunein", "id": e["guide_id"], "name": e.get("text", "?"),
            "subtext": e.get("subtext", ""), "image": image, "url": ""}


def _flatten(body: list) -> list[dict]:
    out = []
    for e in body or []:
        out.append(e)
        out.extend(_flatten(e.get("children") or []))
    return out


def tunein_search(query: str, opener=None) -> list[dict]:
    q = urllib.parse.urlencode({"query": query, "render": "json"})
    body = _json(f"{TUNEIN}/Search.ashx?{q}", opener).get("body")
    return [s for s in map(_tunein_station, _flatten(body)) if s][:SEARCH_LIMIT]


def tunein_local(opener=None) -> list[dict]:
    """TuneIn's 'Local Radio' — by the device's location (IP-based)."""
    body = _json(f"{TUNEIN}/Browse.ashx?c=local&render=json", opener).get("body")
    return [s for s in map(_tunein_station, _flatten(body)) if s][:SEARCH_LIMIT]


def tunein_streams(station_id: str, opener=None) -> list[str]:
    """Current stream URLs for a TuneIn station, most reliable first."""
    q = urllib.parse.urlencode({"id": station_id, "render": "json"})
    body = _json(f"{TUNEIN}/Tune.ashx?{q}", opener).get("body") or []
    entries = [e for e in body if e.get("element") == "audio" and e.get("url")]
    entries.sort(key=lambda e: -int(e.get("reliability") or 0))
    return [e["url"] for e in entries]


# ── Radio Browser ─────────────────────────────────────────────────────────────

def _rb_station(e: dict) -> dict | None:
    url = e.get("url_resolved") or e.get("url")
    if not url or not e.get("stationuuid"):
        return None
    sub = ", ".join(x for x in (e.get("country"), e.get("tags", "").split(",")[0]) if x)
    return {"provider": "rb", "id": e["stationuuid"], "name": (e.get("name") or "?").strip(),
            "subtext": sub, "image": e.get("favicon") or "", "url": url}


def rb_search(query: str, opener=None) -> list[dict]:
    q = urllib.parse.urlencode({"name": query, "limit": SEARCH_LIMIT,
                                "hidebroken": "true", "order": "votes", "reverse": "true"})
    return [s for s in map(_rb_station, _json(f"{RADIO_BROWSER}/stations/search?{q}", opener)) if s]


# ── one front door ────────────────────────────────────────────────────────────

def search(query: str, opener=None) -> tuple[list[dict], str]:
    """Stations matching ``query`` and which directory answered. TuneIn first;
    Radio Browser if TuneIn fails or finds nothing."""
    try:
        found = tunein_search(query, opener)
        if found:
            return found, "tunein"
    except RadioError:
        log.info("tunein search failed — falling back to Radio Browser", exc_info=True)
    return rb_search(query, opener), "rb"


def stream_url(station: dict, opener=None) -> str:
    """A playable stream for ``station``: freshly tuned for TuneIn (addresses
    move), else the saved one. Playlist files (.pls/.m3u) are unwrapped,
    since MPD wants the stream itself."""
    url = ""
    if station.get("provider") == "tunein":
        try:
            urls = tunein_streams(station["id"], opener)
            url = urls[0] if urls else ""
        except RadioError:
            log.info("tunein tune failed — using the saved stream", exc_info=True)
    url = url or station.get("url", "")
    if not url:
        raise RadioError("this station has no stream right now")
    return _unwrap_playlist(url, opener)


def _unwrap_playlist(url: str, opener=None) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    if not path.endswith((".pls", ".m3u", ".m3u8")) or path.endswith(".m3u8"):
        return url                      # HLS (.m3u8) is a stream MPD plays itself
    try:
        text = _get(url, opener).decode("utf-8", "replace")
    except RadioError:
        return url
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("file") and "=" in line:
            line = line.split("=", 1)[1].strip()
        if line.startswith(("http://", "https://")):
            return line
    return url


# ── saved stations ────────────────────────────────────────────────────────────

def _saved_path() -> Path:
    return config.radio_path()


# Kept in memory after the first read: the station list and the launcher ask
# every frame, and the render loop must not touch the disk. Only this module
# writes the file, so the cache can't go stale within the player.
_saved_cache: tuple[Path, list[dict]] | None = None


def saved() -> list[dict]:
    global _saved_cache
    path = _saved_path()
    if _saved_cache is None or _saved_cache[0] != path:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
            items = [s for s in data if isinstance(s, dict) and s.get("id")]
        except (OSError, ValueError):
            items = []
        _saved_cache = (path, items)
    return [dict(s) for s in _saved_cache[1]]


def _write(stations: list[dict]) -> None:
    global _saved_cache
    path = _saved_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stations, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    _saved_cache = (path, [dict(s) for s in stations])


def _key(s: dict) -> tuple:
    return s.get("provider"), s.get("id")


def is_saved(station: dict) -> bool:
    return any(_key(s) == _key(station) for s in saved())


def toggle_saved(station: dict) -> bool:
    """Save or unsave; returns the new state. Newly saved go to the top."""
    current = saved()
    if any(_key(s) == _key(station) for s in current):
        _write([s for s in current if _key(s) != _key(station)])
        return False
    _write([dict(station)] + current)
    return True


def remember_stream(station: dict, url: str) -> None:
    """Keep the last working stream on a saved station (the TuneIn fallback)."""
    current = saved()
    changed = False
    for s in current:
        if _key(s) == _key(station) and s.get("url") != url:
            s["url"] = url
            changed = True
    if changed:
        _write(current)


# ── what is on air ────────────────────────────────────────────────────────────
# The station behind each stream URL handed to MPD, so the player can name it
# (MPD only knows the URL, plus whatever ICY title the stream sends).

_playing: dict[str, dict] = {}


def note_playing(url: str, station: dict) -> None:
    _playing[url] = station
    try:
        p = config.radio_path().with_name("radio-playing.json")
        p.write_text(json.dumps({"url": url, "station": station}, ensure_ascii=False),
                     encoding="utf-8")
    except OSError:
        pass


def station_for(url: str) -> dict | None:
    """The station playing at ``url`` — survives an app restart mid-stream."""
    if url in _playing:
        return _playing[url]
    try:
        p = config.radio_path().with_name("radio-playing.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("url") == url:
            _playing[url] = data["station"]
            return data["station"]
    except (OSError, ValueError, KeyError):
        pass
    return None


# ── logos ─────────────────────────────────────────────────────────────────────

def _logo_base(station: dict) -> Path:
    safe = "".join(c for c in f"{station.get('provider')}_{station.get('id')}"
                   if c.isalnum() or c in "_-")
    return config.art_dir() / "radio" / safe


def logo_path(station: dict) -> Path | None:
    """The cached logo file, if downloaded."""
    base = _logo_base(station)
    for ext in (".png", ".jpg"):
        p = base.with_name(base.name + ext)
        if p.exists():
            return p
    return None


def logo_palette(station: dict) -> list[str] | None:
    """Accent colours from the logo (computed once, at download)."""
    base = _logo_base(station)
    try:
        return json.loads(base.with_name(base.name + ".palette.json").read_text())
    except (OSError, ValueError):
        return None


_fetching: set[str] = set()
_lock = threading.Lock()


def ensure_logo(station: dict) -> Path | None:
    """The cached logo if we have it; otherwise start a download and return
    None (the caller draws a placeholder and asks again later)."""
    found = logo_path(station)
    if found:
        return found
    url = station.get("image")
    if not url:
        return None
    base = _logo_base(station)
    with _lock:
        if str(base) in _fetching:
            return None
        _fetching.add(str(base))

    def work() -> None:
        try:
            data = _get(url)
            ext = ".png" if data[:4] == PNG_MAGIC else ".jpg"
            base.parent.mkdir(parents=True, exist_ok=True)
            _write_palette(data, base)
            tmp = base.with_name(base.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, base.with_name(base.name + ext))
        except Exception:
            log.info("radio logo download failed: %s", url, exc_info=True)
        finally:
            with _lock:
                _fetching.discard(str(base))

    threading.Thread(target=work, daemon=True).start()
    return None


def _write_palette(data: bytes, base: Path) -> None:
    import io

    from PIL import Image

    from musi.library import art
    img = Image.open(io.BytesIO(data)).convert("RGB")
    palette = art._extract_palette(img)
    base.with_name(base.name + ".palette.json").write_text(json.dumps(palette))
