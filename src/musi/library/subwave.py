"""SUB/WAVE — your own AI-DJ radio station (github.com/perminder-klair/subwave).

A SUB/WAVE station streams your Navidrome library through Icecast with an
LLM DJ talking between tracks. musi treats it as a radio station with extras:

  - connect by address ("radio.example.com", "192.168.1.20:7700"),
  - play its MP3 mount like any other station (MPD reads the ICY titles),
  - while it plays, poll ``/api/now-playing`` for the real track, album, the
    on-air DJ and the cover (``/api/cover/<id>``, no Navidrome login needed),
  - send song requests (``POST /api/request``) and follow their outcome.

URL layout: the all-in-one image (Caddy on one port) serves the stream at
``/stream.mp3`` and the API under ``/api/*``. The bring-your-own compose
exposes web :7700, controller :7701 (API at its root) and Icecast :7702 —
``connect`` tries both layouts.

Everything here is blocking network I/O except ``live()``, which starts a
worker and returns at once; call the rest from a worker thread.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from musi.library import config

log = logging.getLogger(__name__)

PROVIDER = "subwave"
TIMEOUT_S = 8
POLL_S = 5.0                       # same pace as SUB/WAVE's own web player
DEFAULT_MOUNT = "/stream.mp3"
BYO_PORTS = (7700, 7701, 7702)     # web, controller, Icecast (compose defaults)
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])


class SubwaveError(Exception):
    pass


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _open(url: str, data: bytes | None = None, opener=None):
    """GET (or POST JSON) → parsed JSON. ``opener(url, data)`` for tests."""
    if opener is not None:
        return opener(url, data)
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET",
        headers={"User-Agent": "musi/1.0", "Accept": "application/json",
                 **({"Content-Type": "application/json"} if data is not None else {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read() or b"null")


def _stream_ok(url: str, opener=None) -> bool:
    """The mount answers with audio (read a few bytes of the endless body)."""
    if opener is not None:
        return bool(opener(url, None))
    req = urllib.request.Request(url, headers={"User-Agent": "musi/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status == 200 and bool(resp.read(16))
    except (urllib.error.URLError, OSError):
        return False


# ── addresses ─────────────────────────────────────────────────────────────────

def normalize(address: str) -> str:
    """'radio.example.com/' → 'http://radio.example.com' (no trailing slash)."""
    a = address.strip()
    if not a:
        raise SubwaveError("enter the station's address")
    if "://" not in a:
        a = "http://" + a
    p = urllib.parse.urlsplit(a)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise SubwaveError("that doesn't look like a web address")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def _with_port(base: str, port: int, path: str = "") -> str:
    p = urllib.parse.urlsplit(base)
    host = p.hostname or ""
    if ":" in host:                                 # IPv6 literal
        host = f"[{host}]"
    return urllib.parse.urlunsplit((p.scheme, f"{host}:{port}", path, "", ""))


def _layouts(base: str) -> list[tuple[str, str]]:
    """(api root, stream root) candidates, most likely first."""
    out = [(base + "/api", base)]                   # all-in-one behind Caddy
    port = urllib.parse.urlsplit(base).port
    if port in BYO_PORTS or port is None:           # bring-your-own compose
        out.append((_with_port(base, 7701), _with_port(base, 7702)))
    return out


# ── connect ───────────────────────────────────────────────────────────────────

def connect(address: str, opener=None) -> dict:
    """Find the station at ``address``; return it as a musi radio station."""
    base = normalize(address)
    last = "no SUB/WAVE station answered there"
    for api, stream_root in _layouts(base):
        try:
            np = _open(api + "/now-playing", opener=opener)
        except urllib.error.HTTPError as exc:
            last = f"the station said HTTP {exc.code}"
            continue
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = f"can't reach it ({getattr(exc, 'reason', exc)})"
            continue
        if not isinstance(np, dict) or "nowPlaying" not in np and "dj" not in np:
            last = "that isn't a SUB/WAVE station"
            continue
        mount = ((np.get("stream") or {}).get("mount") or DEFAULT_MOUNT)
        if not mount.startswith("/"):
            mount = "/" + mount
        stream = stream_root + mount
        if not _stream_ok(stream, opener) and stream_root == base:
            # all-in-one API answered but the mount didn't: try Icecast direct
            alt = _with_port(base, 7702) + mount
            if _stream_ok(alt, opener):
                stream = alt
        dj = np.get("dj") or {}
        name = str(dj.get("station") or "SUB/WAVE").strip() or "SUB/WAVE"
        return {"provider": PROVIDER, "id": base, "name": name,
                "subtext": "Your AI-DJ station", "image": "",
                "url": stream, "api": api}
    raise SubwaveError(last)


# ── the saved station (one) ───────────────────────────────────────────────────

def _path() -> Path:
    return config.radio_path().with_name("subwave.json")


def load() -> dict | None:
    try:
        st = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return st if isinstance(st, dict) and st.get("url") and st.get("api") else None


def save(station: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(station, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def forget() -> None:
    try:
        _path().unlink()
    except OSError:
        pass


def is_subwave(station: dict | None) -> bool:
    return bool(station) and station.get("provider") == PROVIDER


# ── now playing (polled while the station is on) ──────────────────────────────

def parse_now_playing(np: dict, api: str) -> dict:
    """The fields musi shows, from a /now-playing reply."""
    t = (np or {}).get("nowPlaying") or {}
    dj = (np or {}).get("dj") or {}
    show = (np or {}).get("activeShow") or ((np or {}).get("context") or {}).get("activeShow")
    cover_id = t.get("subsonic_id") or t.get("coverArt") or ""
    return {
        "title":  str(t.get("title") or ""),
        "artist": str(t.get("artist") or ""),
        "album":  str(t.get("album") or ""),
        "dj":     str(dj.get("name") or ""),
        "show":   str((show or {}).get("name") or "") if isinstance(show, dict) else "",
        "listeners": np.get("listeners") if isinstance(np.get("listeners"), int) else None,
        "cover_id": str(cover_id),
        "cover_url": f"{api}/cover/{urllib.parse.quote(str(cover_id))}" if cover_id else "",
    }


def _cover_base(cover_id: str) -> Path:
    safe = "".join(c for c in cover_id if c.isalnum() or c in "_-")[:80] or "x"
    return config.art_dir() / "subwave" / safe


def _cached_cover(base: Path) -> Path | None:
    for ext in (".jpg", ".png"):
        p = base.with_name(base.name + ext)
        if p.exists():
            return p
    return None


_state: dict = {}            # api → {"info", "cover", "rev", "at", "busy"}
_state_lock = threading.Lock()


def live(station: dict, opener=None) -> dict:
    """What's on air at ``station`` right now, from the last poll. Starts a
    fresh poll (on a thread) when the last is older than POLL_S. Returns
    {"info": dict | None, "cover": Path | None, "rev": int}; ``rev`` bumps
    whenever info or cover changes, so a screen knows to re-render."""
    api = station.get("api", "")
    with _state_lock:
        s = _state.setdefault(api, {"info": None, "cover": None, "rev": 0,
                                    "at": 0.0, "busy": False})
        due = not s["busy"] and time.monotonic() - s["at"] >= POLL_S
        if due:
            s["busy"] = True
        snap = {"info": s["info"], "cover": s["cover"], "rev": s["rev"]}
    if due:
        threading.Thread(target=_poll, args=(api, opener), daemon=True).start()
    return snap


def _poll(api: str, opener=None) -> None:
    try:
        info = parse_now_playing(_open(api + "/now-playing", opener=opener) or {}, api)
        cover = None
        if info["cover_id"]:
            base = _cover_base(info["cover_id"])
            cover = _cached_cover(base) or _download(info["cover_url"], base, opener)
        with _state_lock:
            s = _state[api]
            if info != s["info"] or cover != s["cover"]:
                s["info"], s["cover"] = info, cover
                s["rev"] += 1
    except Exception:
        log.info("subwave: now-playing poll failed", exc_info=True)
    finally:
        with _state_lock:
            _state[api]["at"] = time.monotonic()
            _state[api]["busy"] = False


def _download(url: str, base: Path, opener=None) -> Path | None:
    """Fetch a cover; saved as .png or .jpg by its magic bytes."""
    if opener is not None:
        data = opener(url, None)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "musi/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = resp.read()
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None
    if data[:4] == PNG_MAGIC:
        ext = ".png"
    elif data[:3] == JPEG_MAGIC:
        ext = ".jpg"
    else:
        return None                     # not an image (an error page, say)
    dest = base.with_name(base.name + ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(bytes(data))
    os.replace(tmp, dest)
    return dest


# ── song requests ─────────────────────────────────────────────────────────────

def request(station: dict, text: str, opener=None) -> str:
    """Ask the DJ for something ("play some Bowie"). Returns the request id."""
    body = json.dumps({"text": text.strip(), "name": "musi"}).encode()
    try:
        r = _open(station["api"] + "/request", data=body, opener=opener) or {}
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise SubwaveError("too many requests — try again in a bit") from exc
        raise SubwaveError(f"the station said HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SubwaveError(f"can't reach the station ({getattr(exc, 'reason', exc)})") from exc
    rid = r.get("requestId") if isinstance(r, dict) else None
    if not rid:
        raise SubwaveError(str((r or {}).get("error") or "request not accepted"))
    return str(rid)


def request_status(station: dict, rid: str, opener=None) -> tuple[str, str]:
    """(status, message): status is pending | resolved | rejected | failed |
    unknown. The message names the matched track when resolved."""
    try:
        r = _open(f"{station['api']}/request/{urllib.parse.quote(rid)}", opener=opener) or {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "unknown", ""
        raise SubwaveError(f"the station said HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SubwaveError(f"can't reach the station ({getattr(exc, 'reason', exc)})") from exc
    status = str(r.get("status") or "pending")
    track = r.get("track") or {}
    if status == "resolved":
        name = " — ".join(x for x in (track.get("artist"), track.get("title")) if x)
        return status, (f"Coming up: {name}" if name
                        else str(r.get("ack") or "The DJ queued it"))
    return status, str(r.get("message") or r.get("ack") or r.get("error") or "")


def request_and_wait(station: dict, text: str, opener=None,
                     tries: int = 20, every: float = 2.0) -> str:
    """Submit, then poll until the DJ decides; a message for the listener."""
    rid = request(station, text, opener)
    for _ in range(tries):
        status, msg = request_status(station, rid, opener)
        if status == "resolved":
            return msg
        if status in ("rejected", "failed"):
            return f"The DJ passed: {msg}" if msg else "The DJ passed on that one"
        if status == "unknown":
            break
        time.sleep(every)
    return "Request sent — the DJ will get to it"
