"""ListenBrainz scrobbling — stdlib client plus an offline-safe listen queue.

The user's token (listenbrainz.org → Settings → User token) lives in a 0600
file next to the other settings. Finished listens go into a small on-disk queue
and are sent from a background thread; anything that fails (offline, server
down) stays queued and goes out on a later flush, so a walk without Wi-Fi
doesn't lose plays.

What counts as a listen (ListenBrainz's own rule) is decided by
player/scrobbler.py; this module only talks to the API.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request

from musi.library import config

API = "https://api.listenbrainz.org/1"
TIMEOUT_S = 15
QUEUE_MAX = 1000         # oldest listens drop past this (months offline)
BATCH = 100              # listens per submit request

log = logging.getLogger(__name__)
_lock = threading.Lock()
_flushing = False


class ListenBrainzError(Exception):
    pass


# ── settings ──────────────────────────────────────────────────────────────────

def _settings_path():
    return config.listenbrainz_path()


def load_settings() -> dict | None:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("token") else None


def save_settings(token: str, user: str) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps({"token": token, "user": user}))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def clear_settings() -> None:
    try:
        _settings_path().unlink()
    except FileNotFoundError:
        pass


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _request(method: str, path: str, token: str, body: dict | None = None,
             opener=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Token {token}", "User-Agent": "musi",
                 "Content-Type": "application/json"})
    try:
        raw = (opener or _open)(req)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ListenBrainzError("token not accepted") from exc
        raise ListenBrainzError(f"server said HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ListenBrainzError(f"can't reach ListenBrainz ({getattr(exc, 'reason', exc)})") from exc
    try:
        return json.loads(raw or b"{}")
    except ValueError as exc:
        raise ListenBrainzError("unexpected reply") from exc


def _open(req) -> bytes:
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def validate_token(token: str, opener=None) -> str:
    """The account name for ``token``; raises ListenBrainzError if it's bad."""
    body = _request("GET", "/validate-token", token, opener=opener)
    if not body.get("valid"):
        raise ListenBrainzError("token not accepted")
    return body.get("user_name", "?")


def _payload(meta: dict) -> dict:
    info = {"media_player": "musi", "submission_client": "musi"}
    if meta.get("duration"):
        info["duration_ms"] = int(float(meta["duration"]) * 1000)
    out = {"artist_name": meta.get("artist") or "Unknown Artist",
           "track_name": meta.get("title") or "Untitled",
           "additional_info": info}
    if meta.get("album"):
        out["release_name"] = meta["album"]
    return out


# ── queue ─────────────────────────────────────────────────────────────────────

def _queue_path():
    return config.listenbrainz_path().with_name("listenbrainz-queue.json")


def _read_queue() -> list[dict]:
    try:
        q = json.loads(_queue_path().read_text(encoding="utf-8"))
        return q if isinstance(q, list) else []
    except (OSError, ValueError):
        return []


def _write_queue(q: list[dict]) -> None:
    path = _queue_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(q[-QUEUE_MAX:]), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        log.warning("listenbrainz: could not save the queue", exc_info=True)


def queued() -> int:
    return len(_read_queue())


def record_listen(meta: dict, listened_at: float) -> None:
    """Queue one finished listen and kick off a flush. Cheap, never blocks."""
    if not load_settings():
        return
    with _lock:
        q = _read_queue()
        q.append({"listened_at": int(listened_at), "track_metadata": _payload(meta)})
        _write_queue(q)
    flush_async()


def playing_now(meta: dict) -> None:
    """Best-effort 'now playing' — not queued, it's stale a minute later."""
    s = load_settings()
    if not s:
        return

    def work() -> None:
        try:
            _request("POST", "/submit-listens", s["token"],
                     {"listen_type": "playing_now",
                      "payload": [{"track_metadata": _payload(meta)}]})
        except ListenBrainzError:
            pass

    threading.Thread(target=work, daemon=True).start()


def flush(opener=None) -> int:
    """Send queued listens, oldest first. Returns how many were accepted;
    whatever fails stays queued for next time."""
    s = load_settings()
    if not s:
        return 0
    sent = 0
    while True:
        with _lock:
            q = _read_queue()
        if not q:
            return sent
        batch = q[:BATCH]
        _request("POST", "/submit-listens", s["token"],
                 {"listen_type": "single" if len(batch) == 1 else "import",
                  "payload": batch}, opener=opener)
        with _lock:
            q = _read_queue()
            _write_queue(q[len(batch):])     # new listens may have arrived
        sent += len(batch)


def flush_async() -> None:
    """flush() on a thread, at most one at a time."""
    global _flushing
    with _lock:
        if _flushing:
            return
        _flushing = True

    def work() -> None:
        global _flushing
        try:
            flush()
        except ListenBrainzError as exc:
            log.info("listenbrainz: kept listens queued (%s)", exc)
        except Exception:
            log.warning("listenbrainz flush failed", exc_info=True)
        finally:
            _flushing = False

    threading.Thread(target=work, daemon=True).start()
