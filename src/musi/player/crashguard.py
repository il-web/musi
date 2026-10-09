"""Crash capture, crash-loop detection and the rollback offer.

Why this exists: the journal lives in RAM (hardening pack), and a native crash
— the SIGBUS family in blit.py — kills the process before Python can log a
word. So a crash used to leave nothing behind, and a bad update left the player
crash-looping with no way back short of SSH.

How it works:
  - Every run, faulthandler and an excepthook write into ``current.txt``. A
    clean exit, a systemctl restart or a power cut write nothing.
  - At the next start, a non-empty ``current.txt`` means the previous run
    crashed: it is appended to ``crash.log`` (capped) and recorded, with the
    version that crashed, in ``state.json``.
  - Several crashes of the same freshly-updated version in a short window is a
    crash loop: the app opens with a prompt offering to roll back to the
    version before the update (screens/rollback.py). The user decides.
  - The one exception: if the new version can't even draw a frame, there is no
    screen to ask on, so after enough failed starts it rolls back by itself.

Stdlib only, and import-safe: install() runs before the rest of the player is
imported, so it still catches an update that broke an import.
"""
from __future__ import annotations

import faulthandler
import json
import logging
import os
import re
import sys
import time
import traceback
from pathlib import Path

from musi.library import config

LOOP_CRASHES  = 3            # crashes of one version …
LOOP_WINDOW_S = 15 * 60      # … within this long = a crash loop → offer rollback
AUTO_CRASHES  = 6            # this many with no frame ever drawn → roll back alone
LOG_CAP       = 64 * 1024    # crash.log keeps the newest ~64 KB
KEEP_CRASHES  = 50

_current = None              # the open file faulthandler writes into


def _dir() -> Path:
    return config.crash_dir()


def _state_path() -> Path:
    return _dir() / "state.json"


def load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logging.warning("crashguard: could not save state", exc_info=True)


# ── per-run setup ─────────────────────────────────────────────────────────────

def install(version: str, now: float | None = None) -> None:
    """Harvest the previous run's crash (if any), then arm capture for this run."""
    global _current
    now = time.time() if now is None else now
    d = _dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    state = load_state()
    _harvest(state)
    state["run"] = {"version": version, "started": now, "ui_ready": False}
    _save_state(state)

    try:
        _current = open(d / "current.txt", "w", encoding="utf-8")
    except OSError:
        return
    faulthandler.enable(file=_current, all_threads=True)
    previous_hook = sys.excepthook

    def hook(etype, value, tb):
        if not issubclass(etype, (KeyboardInterrupt, SystemExit)):
            try:
                traceback.print_exception(etype, value, tb, file=_current)
                _current.flush()
            except Exception:
                pass
        previous_hook(etype, value, tb)

    sys.excepthook = hook


def _harvest(state: dict) -> None:
    cur = _dir() / "current.txt"
    try:
        text = cur.read_text(encoding="utf-8", errors="replace").strip()
        when = cur.stat().st_mtime
    except OSError:
        return
    if not text:
        return
    run = state.get("run") or {}
    version = run.get("version", "?")
    crash = {"t": when, "version": version, "reason": summarize(text),
             "ui_ready": bool(run.get("ui_ready"))}
    state["crashes"] = (state.get("crashes") or [])[-(KEEP_CRASHES - 1):] + [crash]

    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
    _append_log(f"=== {stamp} · version {version} ===\n{text}\n\n")
    try:
        cur.write_text("", encoding="utf-8")
    except OSError:
        pass


def _append_log(entry: str) -> None:
    log = _dir() / "crash.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        old = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        combined = (old + entry)[-LOG_CAP:]
        log.write_text(combined, encoding="utf-8")
    except OSError:
        logging.warning("crashguard: could not write crash.log", exc_info=True)


def mark_ui_ready() -> None:
    """The first frame is on the panel — from here a prompt can be shown."""
    state = load_state()
    if (state.get("run") or {}).get("ui_ready"):
        return
    state.setdefault("run", {})["ui_ready"] = True
    _save_state(state)


# ── reading crashes ───────────────────────────────────────────────────────────

# faulthandler's first line: Linux/Pi, and Windows (dev machine)
_FATAL_HEADERS = ("Fatal Python error:", "Windows fatal exception:")
_FILE_LINE = re.compile(r'File "([^"]+)", line (\d+)(?:, in |\s+in )(\S+)')


def summarize(text: str) -> str:
    """One line for the UI: what happened, and where in musi's own code."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "unknown crash"
    fatal = next((h for h in _FATAL_HEADERS if lines[0].startswith(h)), None)
    if fatal:                                             # faulthandler output
        what = lines[0][len(fatal):].strip()
        frames = _FILE_LINE.findall(text)                 # most recent call FIRST
        frames = [f for f in frames if "musi" in f[0]] or frames
        where = frames[0] if frames else None
    else:
        what = lines[-1]                                  # "ValueError: …"
        frames = _FILE_LINE.findall(text)                 # most recent call LAST
        frames = [f for f in frames if "musi" in f[0]] or frames
        where = frames[-1] if frames else None
    if where:
        return f"{what} — {Path(where[0]).name}:{where[1]} ({where[2]})"
    return what


def last_crash(state: dict | None = None) -> dict | None:
    crashes = (state or load_state()).get("crashes") or []
    return crashes[-1] if crashes else None


def read_log() -> str:
    try:
        return (_dir() / "crash.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _recent(state: dict, version: str, window: float, now: float) -> list[dict]:
    return [c for c in state.get("crashes") or []
            if c.get("version") == version and now - c.get("t", 0) <= window]


# ── updates & rollback ────────────────────────────────────────────────────────

def note_update(previous: str, new: str, now: float | None = None) -> None:
    """Remember what an update replaced, so it can be undone."""
    state = load_state()
    state["update"] = {"from": previous, "to": new,
                       "t": time.time() if now is None else now}
    _save_state(state)


def rollback_target(version: str, state: dict | None = None) -> str | None:
    """The version to go back to, if ``version`` arrived through an update."""
    upd = (state or load_state()).get("update") or {}
    if upd.get("from") and upd.get("to") and _same(upd["to"], version):
        return upd["from"]
    return None


def offer(version: str, now: float | None = None) -> dict | None:
    """Crash-loop on a freshly updated version → what the prompt should say."""
    now = time.time() if now is None else now
    state = load_state()
    if _same(state.get("declined", ""), version):
        return None
    target = rollback_target(version, state)
    recent = _recent(state, version, LOOP_WINDOW_S, now)
    if not target or len(recent) < LOOP_CRASHES:
        return None
    return {"version": version, "target": target, "count": len(recent),
            "reason": recent[-1].get("reason", "")}


def must_auto_rollback(version: str, now: float | None = None) -> str | None:
    """No frame has ever been drawn on this version and it keeps dying: the
    prompt can't be shown, so the only way out is to roll back unasked."""
    now = time.time() if now is None else now
    state = load_state()
    target = rollback_target(version, state)
    if not target:
        return None
    crashes = [c for c in state.get("crashes") or [] if _same(c.get("version", ""), version)]
    if len(crashes) < AUTO_CRASHES or any(c.get("ui_ready") for c in crashes):
        return None
    if now - crashes[-AUTO_CRASHES].get("t", 0) > LOOP_WINDOW_S:
        return None
    return target


def rolled_back(target: str) -> None:
    """After a rollback the update record is spent: the version we are now on
    was not 'freshly updated to', so it must never offer a rollback itself."""
    state = load_state()
    upd = state.pop("update", None) or {}
    state["rolled_back_from"] = upd.get("to")
    _save_state(state)


def decline(version: str) -> None:
    """'Keep this version' — don't ask again about it."""
    state = load_state()
    state["declined"] = version
    _save_state(state)


def _same(a: str, b: str) -> bool:
    """Short and full commit ids name the same commit."""
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))
