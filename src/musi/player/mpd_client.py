"""MPD client wrapper.

Wraps python-mpd2 with:
  - Auto-reconnect on dropped connection
  - Absolute <-> relative path conversion
  - Clean PlayerStatus dataclass for the UI
  - play_paths() to replace the queue and start playback
  - stored-playlist CRUD, and Favourites as one reserved playlist
"""

from __future__ import annotations

import functools
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Optional

import mpd

# The Favourites list is just an ordinary stored playlist with a fixed name; the
# heart toggle on Now Playing adds/removes the current track in it.
FAVORITES = "Favorites"

# MPD stores playlists as files under playlist_directory, so a name has to be a
# safe single path segment. MPD itself rejects "/" and a leading ".", but it is
# friendlier to sanitise here than to surface a protocol error.
_NAME_MAX = 40


def _safe_playlist_name(name: str) -> str:
    """Trim a user-typed playlist name to something MPD will accept as a file."""
    cleaned = re.sub(r'[/\\\x00-\x1f]', "", str(name)).strip().lstrip(".")
    return cleaned[:_NAME_MAX].strip()


def _tag(song: dict, key: str, default: str = "") -> str:
    """Collapse an MPD tag to a single string.

    MPD/python-mpd2 returns a *list* when a song has multiple values for a tag
    (e.g. several Artist entries on a collab), which would crash the text
    renderer. Join those so the UI always receives a string, never a list.
    """
    val = song.get(key, default)
    if isinstance(val, list):
        return ", ".join(str(v) for v in val) or default
    return str(val) if val is not None else default


@dataclass
class PlayerStatus:
    state: str              # "play" | "pause" | "stop"
    path: Optional[str]     # absolute path of current track (or None)
    title: str
    artist: str
    album: str
    elapsed: float          # seconds into current track
    duration: float         # total track length in seconds
    volume: int             # 0 – 100
    shuffle: bool
    repeat: bool
    queue_pos: int          # 0-based position in queue
    queue_len: int
    connected: bool = True

    @property
    def progress(self) -> float:
        """0.0 – 1.0 playback progress."""
        return (self.elapsed / self.duration) if self.duration > 0 else 0.0

    @staticmethod
    def disconnected() -> "PlayerStatus":
        return PlayerStatus(
            state="stop", path=None, title="Not connected", artist="",
            album="", elapsed=0, duration=0, volume=0,
            shuffle=False, repeat=False, queue_pos=0, queue_len=0,
            connected=False,
        )


@dataclass
class QueueItem:
    pos:    int   # 0-based position in the MPD queue
    title:  str
    artist: str
    path:   str = ""   # absolute path — lets a queue row be added to a playlist


@dataclass
class PlaylistInfo:
    name:        str
    track_count: int


def _synchronized(fn):
    """Serialise access to the MPD socket.

    python-mpd2 is not thread-safe: a command writes to the socket and then
    reads the reply, so two overlapping callers desync the protocol. The
    loading screen reconnects from a daemon thread every 0.4 s while the main
    loop polls every 1.0 s, so that overlap is the normal startup case.
    """
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class MusiMPDClient:
    """Thread-safe(ish) MPD client for the musi player UI."""

    # after a failed connect, don't retry for this long — a dead MPD would
    # otherwise block the UI thread on every poll (connects run synchronously)
    RETRY_BACKOFF_S = 3.0

    def __init__(
        self,
        music_root: Path,
        host: str = "127.0.0.1",   # not "localhost" — avoids a 2 s IPv6 timeout
        port: int = 6600,
    ) -> None:
        self._music_root = Path(music_root)
        self._host = host
        self._port = port
        self._lock = threading.RLock()   # see _synchronized
        self._client = mpd.MPDClient()
        self._client.timeout = 2
        self._connected = False
        self._next_retry = 0.0

    # ── connection ────────────────────────────────────────────────────────────

    @_synchronized
    def connect(self) -> bool:
        # Clear any socket left attached by a failed command. python-mpd2
        # refuses to connect while one is (base.py: 'Already connected'), and
        # every error path below drops our _connected flag without closing it —
        # so without this, one stalled MPD wedges the UI as permanently
        # disconnected until the process restarts.
        try:
            self._client.disconnect()
        except Exception:
            pass
        try:
            self._client.connect(self._host, self._port)
            self._connected = True
            self._next_retry = 0.0
            return True
        except Exception:
            self._connected = False
            self._next_retry = time() + self.RETRY_BACKOFF_S
            return False

    @_synchronized
    def disconnect(self) -> None:
        try:
            self._client.close()
            self._client.disconnect()
        except Exception:
            import logging
            logging.warning('Ignored exception', exc_info=True)
        self._connected = False

    @_synchronized
    def _ensure(self) -> bool:
        """Reconnect if needed. Returns True if connected."""
        if self._connected:
            try:
                self._client.ping()
                return True
            except Exception:
                self._connected = False
        if time() < self._next_retry:
            return False
        return self.connect()

    # ── status ────────────────────────────────────────────────────────────────

    @_synchronized
    def poll(self) -> PlayerStatus:
        """Fetch current player status. Returns disconnected stub on error."""
        if not self._ensure():
            return PlayerStatus.disconnected()
        try:
            status = self._client.status()
            song   = self._client.currentsong()

            state    = status.get("state", "stop")
            volume   = int(status.get("volume", 0))
            shuffle  = status.get("random", "0") == "1"
            repeat   = status.get("repeat",  "0") == "1"
            elapsed  = float(status.get("elapsed",  0))
            duration = float(status.get("duration", 0))
            queue_pos = int(status.get("song",    0)) if "song"    in status else 0
            queue_len = int(status.get("playlistlength", 0))

            rel_path = song.get("file", "")
            abs_path = str(self._music_root / rel_path) if rel_path else None

            return PlayerStatus(
                state=state,
                path=abs_path,
                title=_tag(song, "title", Path(rel_path).stem if rel_path else ""),
                artist=_tag(song, "artist", ""),
                album=_tag(song, "album", ""),
                elapsed=elapsed,
                duration=duration,
                volume=volume,
                shuffle=shuffle,
                repeat=repeat,
                queue_pos=queue_pos,
                queue_len=queue_len,
                connected=True,
            )
        except Exception:
            self._connected = False
            return PlayerStatus.disconnected()

    # ── playback controls ─────────────────────────────────────────────────────

    @_synchronized
    def play_pause(self) -> None:
        if not self._ensure():
            return
        try:
            status = self._client.status()
            if status.get("state") == "play":
                self._client.pause(1)
            else:
                self._client.play()
        except Exception:
            self._connected = False

    @_synchronized
    def pause(self) -> None:
        """Pause playback (no-op if already paused/stopped)."""
        self._cmd(lambda: self._client.pause(1))

    @_synchronized
    def next_track(self) -> None:
        self._cmd(lambda: self._client.next())

    @_synchronized
    def prev_track(self) -> None:
        self._cmd(lambda: self._client.previous())

    @_synchronized
    def seek(self, seconds: float) -> None:
        self._cmd(lambda: self._client.seekcur(str(seconds)))

    @_synchronized
    def set_volume(self, volume: int) -> None:
        self._cmd(lambda: self._client.setvol(max(0, min(100, volume))))

    @_synchronized
    def toggle_shuffle(self) -> None:
        if not self._ensure():
            return
        try:
            current = self._client.status().get("random", "0")
            self._client.random(0 if current == "1" else 1)
        except Exception:
            self._connected = False

    @_synchronized
    def set_shuffle(self, on: bool) -> None:
        """Set MPD random mode explicitly (album screen Play/Shuffle)."""
        self._cmd(lambda: self._client.random(1 if on else 0))

    @_synchronized
    def set_crossfade(self, seconds: int) -> None:
        """Blend consecutive tracks over ``seconds``. Zero disables it.

        MPD keeps this in its own state file, so it survives a restart of the
        daemon but not a change made while the daemon was down — which is why
        the UI re-applies the stored preference on startup.
        """
        self._cmd(lambda: self._client.crossfade(int(seconds)))

    @_synchronized
    def toggle_repeat(self) -> None:
        if not self._ensure():
            return
        try:
            current = self._client.status().get("repeat", "0")
            self._client.repeat(0 if current == "1" else 1)
        except Exception:
            self._connected = False

    @_synchronized
    def db_update(self) -> None:
        """Tell MPD to rescan its music directory."""
        if not self._ensure():
            return
        try:
            self._client.update()
        except Exception:
            import logging
            logging.warning('Ignored exception', exc_info=True)

    # ── queue management ──────────────────────────────────────────────────────

    @_synchronized
    def play_paths(self, paths: list[Path | str], start_index: int = 0) -> None:
        """Replace the MPD queue with the given absolute paths and start playing."""
        if not self._ensure():
            return
        try:
            self._client.clear()
            for p in paths:
                rel = self._to_relative(Path(p))
                self._client.add(rel)
            if paths:
                self._client.play(start_index)
        except Exception:
            self._connected = False

    @_synchronized
    def queue(self) -> list["QueueItem"]:
        """Return the current play queue (the up-next list)."""
        if not self._ensure():
            return []
        try:
            songs = self._client.playlistinfo()
        except Exception:
            self._connected = False
            return []
        return [
            QueueItem(
                pos    = int(s.get("pos", 0)),
                title  = _tag(s, "title", Path(s.get("file", "")).stem),
                artist = _tag(s, "artist", ""),
                path   = str(self._music_root / s["file"]) if s.get("file") else "",
            )
            for s in songs
        ]

    @_synchronized
    def play_pos(self, pos: int) -> None:
        """Jump to and play the track at queue position ``pos``."""
        self._cmd(lambda: self._client.play(pos))

    @_synchronized
    def queue_next(self, paths: list[Path | str]) -> None:
        """Insert tracks right after the currently playing one."""
        if not self._ensure():
            return
        try:
            pos = int(self._client.status().get("song", -1)) + 1
            for i, p in enumerate(paths):
                self._client.addid(self._to_relative(Path(p)), pos + i)
        except Exception:
            self._connected = False

    @_synchronized
    def queue_add(self, paths: list[Path | str]) -> None:
        """Append tracks to the end of the queue."""
        if not self._ensure():
            return
        try:
            for p in paths:
                self._client.add(self._to_relative(Path(p)))
        except Exception:
            self._connected = False

    @_synchronized
    def remove_pos(self, pos: int) -> None:
        """Remove the track at queue position ``pos``."""
        self._cmd(lambda: self._client.delete(pos))

    @_synchronized
    def move(self, from_pos: int, to_pos: int) -> None:
        """Reorder: move a queued track from one position to another."""
        if from_pos == to_pos:
            return
        self._cmd(lambda: self._client.move(from_pos, to_pos))

    # ── stored playlists ──────────────────────────────────────────────────────

    @_synchronized
    def list_playlists(self) -> list["PlaylistInfo"]:
        """All stored playlists, Favourites first, then case-insensitive name."""
        if not self._ensure():
            return []
        try:
            names = [p.get("playlist", "") for p in self._client.listplaylists()]
        except Exception:
            self._connected = False
            return []
        out: list[PlaylistInfo] = []
        for name in names:
            if not name:
                continue
            try:
                count = len(self._client.listplaylist(name))
            except Exception:
                count = 0
            out.append(PlaylistInfo(name, count))
        out.sort(key=lambda p: (p.name != FAVORITES, p.name.lower()))
        return out

    @_synchronized
    def playlist_tracks(self, name: str) -> list[dict]:
        """The tracks in a stored playlist, as {path, title, artist, duration}."""
        if not self._ensure():
            return []
        try:
            songs = self._client.listplaylistinfo(name)
        except Exception:
            return []
        out: list[dict] = []
        for s in songs:
            rel = s.get("file", "")
            out.append({
                "path":     str(self._music_root / rel) if rel else "",
                "title":    _tag(s, "title", Path(rel).stem if rel else ""),
                "artist":   _tag(s, "artist", ""),
                "duration": float(s.get("duration", s.get("time", 0)) or 0),
            })
        return out

    @_synchronized
    def playlist_add(self, name: str, paths: list[Path | str]) -> None:
        """Append tracks to a stored playlist, creating it if it does not exist."""
        if not self._ensure():
            return
        name = _safe_playlist_name(name)
        if not name:
            return
        try:
            for p in paths:
                self._client.playlistadd(name, self._to_relative(Path(p)))
        except Exception:
            self._connected = False

    @_synchronized
    def playlist_remove_at(self, name: str, pos: int) -> None:
        self._cmd(lambda: self._client.playlistdelete(name, pos))

    @_synchronized
    def playlist_move(self, name: str, from_pos: int, to_pos: int) -> None:
        if from_pos == to_pos:
            return
        self._cmd(lambda: self._client.playlistmove(name, from_pos, to_pos))

    @_synchronized
    def playlist_rename(self, old: str, new: str) -> None:
        new = _safe_playlist_name(new)
        if not new or new == old:
            return
        self._cmd(lambda: self._client.rename(old, new))

    @_synchronized
    def playlist_delete(self, name: str) -> None:
        self._cmd(lambda: self._client.rm(name))

    @_synchronized
    def play_playlist(self, name: str, start_index: int = 0,
                      shuffle: bool = False) -> None:
        """Replace the queue with a stored playlist and start playing."""
        if not self._ensure():
            return
        try:
            self._client.clear()
            self._client.load(name)
            self._client.random(1 if shuffle else 0)
            self._client.play(start_index)
        except Exception:
            self._connected = False

    @_synchronized
    def queue_playlist(self, name: str) -> None:
        """Append a stored playlist to the end of the current queue."""
        self._cmd(lambda: self._client.load(name))

    @_synchronized
    def save_queue_as(self, name: str) -> None:
        """Save the current queue as a stored playlist, replacing any namesake."""
        if not self._ensure():
            return
        name = _safe_playlist_name(name)
        if not name:
            return
        try:
            self._client.rm(name)
        except Exception:
            pass                       # no namesake to replace — fine
        self._cmd(lambda: self._client.save(name))

    # ── favourites (a reserved stored playlist) ───────────────────────────────

    def _favorites_rel(self) -> list[str]:
        """Relative paths in the Favourites playlist, [] if it does not exist."""
        try:
            return list(self._client.listplaylist(FAVORITES))
        except Exception:
            return []

    @_synchronized
    def is_favorite(self, abs_path: str) -> bool:
        if not abs_path or not self._ensure():
            return False
        return self._to_relative(Path(abs_path)) in self._favorites_rel()

    @_synchronized
    def toggle_favorite(self, abs_path: str) -> bool:
        """Add or remove a track in Favourites. Returns the new favourite state."""
        if not abs_path or not self._ensure():
            return False
        rel = self._to_relative(Path(abs_path))
        current = self._favorites_rel()
        try:
            if rel in current:
                self._client.playlistdelete(FAVORITES, current.index(rel))
                return False
            self._client.playlistadd(FAVORITES, rel)
            return True
        except Exception:
            self._connected = False
            return rel in current

    # ── play history ──────────────────────────────────────────────────────────

    @_synchronized
    def record_play(self, db_conn: sqlite3.Connection, abs_path: str) -> None:
        """Write a play_history row for the given track path."""
        try:
            row = db_conn.execute(
                "SELECT id FROM tracks WHERE path = ?", (abs_path,)
            ).fetchone()
            if row:
                db_conn.execute(
                    "INSERT INTO play_history (track_id) VALUES (?)", (row[0],)
                )
                db_conn.commit()
        except Exception:
            import logging
            logging.warning('Ignored exception', exc_info=True)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _to_relative(self, path: Path) -> str:
        """Convert absolute path to MPD-relative path."""
        try:
            return str(path.relative_to(self._music_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    @_synchronized
    def _cmd(self, fn) -> None:
        if not self._ensure():
            return
        try:
            fn()
        except Exception:
            self._connected = False
