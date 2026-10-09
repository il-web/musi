"""AirPlay — what the phone is playing through musi, and controlling it.

shairport-sync (musi-airplay.service, see pi/shairport-sync.conf) does the
audio. This module is the player's view of it:

  - active(): the session hook's flag file (/tmp/musi-airplay) exists — a
    phone's session owns the output (playing, or briefly paused: the session
    outlives a pause, see pi/shairport-sync.conf) and MPD has been stopped.
  - A reader thread follows shairport-sync's metadata pipe for the title,
    artist, album, cover art and play position, and overlays them on the
    player status, so Now Playing and the mini bar show the phone's song.
  - command(): play/pause/next/previous go back to the phone over MPRIS on
    the session bus.
  - end_session(): musi wants the speaker back (you pressed play on your own
    music) — restart the receiver, which drops the phone.

Metadata items look like
  <item><type>636f7265</type><code>6d696e6d</code><length>5</length>
  <data encoding="base64">SGVsbG8=</data></item>
type/code are 4 ASCII chars in hex: core/minm = title, core/asar = artist,
core/asal = album, ssnc/PICT = cover, ssnc/prgr = "start/now/end" in RTP
frames (44.1 kHz), ssnc/pfls / ssnc/prsm = paused / resumed.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import replace

FLAG = "/tmp/musi-airplay"
PIPE = "/tmp/shairport-sync-metadata"
PATH_PREFIX = "airplay://"
RATE = 44100
MPRIS = ("org.mpris.MediaPlayer2.ShairportSync", "/org/mpris/MediaPlayer2",
         "org.mpris.MediaPlayer2.Player")

_ITEM = re.compile(
    r"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
    r"(?:\s*<data encoding=\"base64\">\s*([^<]*?)\s*</data>)?\s*</item>", re.S)

log = logging.getLogger(__name__)
_lock = threading.Lock()
_meta = {"title": "", "artist": "", "album": "", "art": b"", "art_rev": 0,
         "track": 0, "paused": False, "start": None, "now": None, "end": None,
         "at": 0.0, "source": ""}
_reader: threading.Thread | None = None


def active() -> bool:
    return os.path.exists(FLAG)


# ── metadata ──────────────────────────────────────────────────────────────────

def _code(hexs: str) -> str:
    try:
        return bytes.fromhex(hexs).decode("ascii", "replace")
    except ValueError:
        return "????"


def feed(text: str) -> str:
    """Apply every complete item in ``text``; returns the unparsed tail."""
    last = 0
    for m in _ITEM.finditer(text):
        last = m.end()
        kind, code = _code(m.group(1)), _code(m.group(2))
        data = base64.b64decode(m.group(4)) if m.group(4) else b""
        _apply(kind, code, data)
    return text[last:]


def _apply(kind: str, code: str, data: bytes) -> None:
    with _lock:
        if kind == "core" and code in ("minm", "asar", "asal"):
            key = {"minm": "title", "asar": "artist", "asal": "album"}[code]
            value = data.decode("utf-8", "replace").strip()
            if value != _meta[key]:
                _meta[key] = value
                if key in ("title", "artist"):
                    _meta["track"] += 1         # a new song: Now Playing animates
        elif kind == "ssnc":
            if code == "PICT":
                _meta["art"], _meta["art_rev"] = data, _meta["art_rev"] + 1
            elif code == "prgr":
                try:
                    start, now, end = (int(x) for x in data.decode().split("/"))
                except ValueError:
                    return
                _meta.update(start=start, now=now, end=end, at=time.monotonic())
            elif code == "pfls":
                _set_paused(True)
            elif code in ("prsm", "pbeg"):
                _set_paused(False)
            elif code == "snam":
                _meta["source"] = data.decode("utf-8", "replace")


def _set_paused(paused: bool) -> None:
    """Caller holds _lock. Pausing freezes the position where playback really
    is — the last report plus the time played since — not at the report."""
    now = time.monotonic()
    if paused and not _meta["paused"] and _meta["now"] is not None:
        played = int((now - _meta["at"]) * RATE)
        _meta["now"] = min(_meta["now"] + played, _meta["end"] or _meta["now"] + played)
    _meta["paused"] = paused
    _meta["at"] = now


def snapshot() -> dict:
    with _lock:
        return dict(_meta)


def position(now: float | None = None) -> tuple[float, float]:
    """(elapsed, duration) in seconds, extrapolated since the last report."""
    m = snapshot()
    if m["start"] is None or m["end"] is None or m["end"] <= m["start"]:
        return 0.0, 0.0
    duration = (m["end"] - m["start"]) / RATE
    elapsed = (m["now"] - m["start"]) / RATE
    if not m["paused"]:
        elapsed += (time.monotonic() if now is None else now) - m["at"]
    return max(0.0, min(elapsed, duration)), duration


def overlay(status):
    """The player status, showing the phone's song instead of MPD's."""
    m = snapshot()
    elapsed, duration = position()
    return replace(
        status,
        state="pause" if m["paused"] else "play",
        path=f"{PATH_PREFIX}{m['track']}",
        title=m["title"] or "AirPlay",
        artist=m["artist"] or (m["source"] or "iPhone"),
        album=m["album"],
        elapsed=elapsed,
        duration=duration,
        connected=True,
    )


_cover_cache: tuple[int, tuple, object] | None = None


def cover(size: tuple[int, int]):
    """The current cover as an opaque pygame surface (or None)."""
    global _cover_cache
    m = snapshot()
    if not m["art"]:
        return None
    if _cover_cache and _cover_cache[0] == m["art_rev"] and _cover_cache[1] == size:
        return _cover_cache[2]
    import pygame
    try:
        img = pygame.image.load(io.BytesIO(m["art"]))
        flat = pygame.Surface(img.get_size())
        flat.fill((0, 0, 0))
        flat.blit(img, (0, 0))              # opaque before scaling (blit.py)
        surf = pygame.transform.smoothscale(flat.convert(), size)
    except (pygame.error, ValueError):
        surf = None
    _cover_cache = (m["art_rev"], size, surf)
    return surf


# ── reader thread ─────────────────────────────────────────────────────────────

def start_reader() -> None:
    """Follow the metadata pipe for the life of the process (Linux only)."""
    global _reader
    if _reader is not None or sys.platform == "win32":
        return

    def run() -> None:
        while True:
            if not os.path.exists(PIPE):
                time.sleep(5)               # receiver not installed / not up yet
                continue
            try:
                with open(PIPE, "r", encoding="utf-8", errors="replace") as f:
                    tail = ""
                    while True:
                        chunk = f.read(4096)
                        if not chunk:
                            break           # writer went away — reopen
                        tail = feed(tail + chunk)
                        if len(tail) > 4 * 1024 * 1024:
                            tail = ""       # a broken stream must not eat RAM
            except OSError:
                log.info("airplay: metadata pipe error", exc_info=True)
                time.sleep(2)

    _reader = threading.Thread(target=run, name="airplay-metadata", daemon=True)
    _reader.start()


# ── control ───────────────────────────────────────────────────────────────────

def command(name: str) -> None:
    """PlayPause / Next / Previous to the phone, off the UI thread."""
    def work() -> None:
        try:
            r = subprocess.run(["busctl", "--user", "call", *MPRIS, name],
                               capture_output=True, timeout=4)
            if r.returncode != 0:
                log.info("airplay: %s failed: %s", name, r.stderr[-200:])
        except Exception:
            log.info("airplay: %s failed", name, exc_info=True)

    if name == "PlayPause":                 # instant feedback; the phone confirms
        with _lock:
            _set_paused(not _meta["paused"])
    threading.Thread(target=work, daemon=True).start()


def end_session() -> None:
    """Take the speaker back for musi's own music: restarting the receiver
    drops the phone. The flag goes too — a killed session never runs its
    'end' hook. Blocking (a second or two): call before starting MPD."""
    try:
        os.remove(FLAG)
    except FileNotFoundError:
        pass
    try:
        subprocess.run(["systemctl", "--user", "restart", "musi-airplay"],
                       capture_output=True, timeout=10)
    except Exception:
        log.info("airplay: could not restart the receiver", exc_info=True)
