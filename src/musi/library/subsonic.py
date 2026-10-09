"""Subsonic API client — Navidrome, Gonic, Airsonic, Ampache all speak it.

Stdlib only (urllib + json), like art_fetch and lyrics. Auth is the Subsonic
token scheme: every request carries ``t = md5(password + salt)`` with a fresh
random salt, so the password itself never crosses the network. It does have to
be stored on the device to mint tokens — hence the 0600 settings file.

The login lives in config.subsonic_path():

    {"url": "http://192.168.1.20:4533", "username": "me", "password": "…"}

plus a few bookkeeping keys the sync writes (last_sync, track_count).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from musi.library import config

API_VERSION = "1.16.1"
CLIENT_NAME = "musi"
TIMEOUT_S   = 15

log = logging.getLogger(__name__)


class SubsonicError(Exception):
    """The server answered, but with a Subsonic error (bad login, not found…)
    — or could not be reached at all (code None)."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


# ── stored login ──────────────────────────────────────────────────────────────

def load_settings() -> dict | None:
    """The saved login, or None if no server is set up (or the file is junk)."""
    try:
        data = json.loads(config.subsonic_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("subsonic.json unreadable — treating as not set up", exc_info=True)
        return None
    if not isinstance(data, dict) or not data.get("url") or not data.get("username"):
        return None
    return data


def save_settings(data: dict) -> None:
    """Write atomically, owner-only — the file holds a password."""
    path = config.subsonic_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def update_settings(**changes) -> dict:
    """Merge ``changes`` into the saved settings (None deletes a key)."""
    data = load_settings() or {}
    for k, v in changes.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    save_settings(data)
    return data


def clear_settings() -> None:
    try:
        config.subsonic_path().unlink()
    except FileNotFoundError:
        pass


def normalize_url(url: str) -> str:
    """'192.168.1.20:4533/' → 'http://192.168.1.20:4533' — typed on a tiny
    keyboard, so be forgiving about the scheme and the trailing slash."""
    url = url.strip()
    if url and "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


# ── client ────────────────────────────────────────────────────────────────────

class Client:
    def __init__(self, url: str, username: str, password: str,
                 opener=None) -> None:
        self.url      = normalize_url(url)
        self.username = username
        self._password = password
        # injectable for tests: callable(url) -> bytes
        self._open = opener or _http_get

    @classmethod
    def from_settings(cls, settings: dict | None = None) -> "Client | None":
        s = settings if settings is not None else load_settings()
        if not s:
            return None
        return cls(s["url"], s["username"], s.get("password", ""))

    # ── url building ──────────────────────────────────────────────────────────

    def _auth(self) -> dict:
        salt = secrets.token_hex(6)
        token = hashlib.md5((self._password + salt).encode("utf-8")).hexdigest()
        return {"u": self.username, "t": token, "s": salt,
                "v": API_VERSION, "c": CLIENT_NAME}

    def url_for(self, method: str, **params) -> str:
        """Fully signed URL — also what the stream redirect hands to MPD."""
        q = self._auth()
        q.update({k: v for k, v in params.items() if v is not None})
        return f"{self.url}/rest/{method}?{urllib.parse.urlencode(q)}"

    def stream_url(self, song_id: str, max_bitrate: int = 0) -> str:
        # format=raw: the original file, which the server can serve with Range
        # support, so seeking works. Transcoded streams can't seek in MPD.
        if max_bitrate:
            return self.url_for("stream", id=song_id, maxBitRate=max_bitrate)
        return self.url_for("stream", id=song_id, format="raw")

    def cover_art_url(self, cover_id: str, size: int = 600) -> str:
        return self.url_for("getCoverArt", id=cover_id, size=size)

    # ── calls ─────────────────────────────────────────────────────────────────

    def call(self, method: str, **params) -> dict:
        """One JSON API call; returns the 'subsonic-response' body."""
        url = self.url_for(method, f="json", **params)
        try:
            raw = self._open(url)
        except urllib.error.HTTPError as exc:
            raise SubsonicError(f"server said HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise SubsonicError(f"can't reach server ({reason})") from exc
        try:
            body = json.loads(raw)["subsonic-response"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SubsonicError("not a Subsonic server") from exc
        if body.get("status") != "ok":
            err = body.get("error") or {}
            raise SubsonicError(err.get("message", "request failed"), err.get("code"))
        return body

    def ping(self) -> None:
        """Raises SubsonicError unless the URL and login are good."""
        self.call("ping")

    def albums(self, page: int = 500):
        """Every album (getAlbumList2, alphabetical), paged."""
        offset = 0
        while True:
            body = self.call("getAlbumList2", type="alphabeticalByName",
                             size=page, offset=offset)
            batch = (body.get("albumList2") or {}).get("album") or []
            yield from batch
            if len(batch) < page:
                return
            offset += page

    def album_songs(self, album_id: str) -> list[dict]:
        body = self.call("getAlbum", id=album_id)
        return (body.get("album") or {}).get("song") or []

    def all_songs(self, page: int = 500):
        """Every song via an empty search3 — one request per 500 songs instead
        of one per album. Navidrome supports it; servers that return nothing
        are handled by the caller falling back to album_songs()."""
        offset = 0
        while True:
            body = self.call("search3", query="", songCount=page, songOffset=offset,
                             albumCount=0, artistCount=0)
            batch = (body.get("searchResult3") or {}).get("song") or []
            yield from batch
            if len(batch) < page:
                return
            offset += page

    def cover_art(self, cover_id: str, size: int = 600) -> bytes:
        try:
            return self._open(self.cover_art_url(cover_id, size))
        except (urllib.error.URLError, OSError) as exc:
            raise SubsonicError(f"cover download failed ({exc})") from exc

    def scrobble(self, song_id: str, submission: bool = True) -> None:
        """Tell the server a song was played (its play counts, Last.fm…), or
        with submission=False, that it is playing now."""
        self.call("scrobble", id=song_id,
                  submission="true" if submission else "false")


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "musi"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def scrobble_async(path: str, submission: bool = True) -> None:
    """Report a play (or 'now playing') of one of our stream URLs, off the
    calling thread. When a play counts is player/scrobbler.py's call.

    Fire-and-forget: a scrobble that fails (offline, server down) is only a
    missed play count, never worth stalling the UI loop over.
    """
    import threading

    from musi.library import remote

    sid = remote.song_id(path)
    if not sid:
        return

    def work() -> None:
        try:
            client = Client.from_settings()
            if client:
                client.scrobble(sid, submission)
        except Exception:
            log.info("scrobble failed", exc_info=True)

    threading.Thread(target=work, daemon=True).start()
