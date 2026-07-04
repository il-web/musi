"""MPD client wrapper.

Wraps python-mpd2 with:
  - Auto-reconnect on dropped connection
  - Absolute <-> relative path conversion
  - Clean PlayerStatus dataclass for the UI
  - play_paths() to replace the queue and start playback
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Optional

import mpd


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
        self._client = mpd.MPDClient()
        self._client.timeout = 2
        self._connected = False
        self._next_retry = 0.0

    # ── connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._client.connect(self._host, self._port)
            self._connected = True
            self._next_retry = 0.0
            return True
        except Exception:
            self._connected = False
            self._next_retry = time() + self.RETRY_BACKOFF_S
            return False

    def disconnect(self) -> None:
        try:
            self._client.close()
            self._client.disconnect()
        except Exception:
            import logging
            logging.warning('Ignored exception', exc_info=True)
        self._connected = False

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

    def pause(self) -> None:
        """Pause playback (no-op if already paused/stopped)."""
        self._cmd(lambda: self._client.pause(1))

    def next_track(self) -> None:
        self._cmd(lambda: self._client.next())

    def prev_track(self) -> None:
        self._cmd(lambda: self._client.previous())

    def seek(self, seconds: float) -> None:
        self._cmd(lambda: self._client.seekcur(str(seconds)))

    def set_volume(self, volume: int) -> None:
        self._cmd(lambda: self._client.setvol(max(0, min(100, volume))))

    def toggle_shuffle(self) -> None:
        if not self._ensure():
            return
        try:
            current = self._client.status().get("random", "0")
            self._client.random(0 if current == "1" else 1)
        except Exception:
            self._connected = False

    def toggle_repeat(self) -> None:
        if not self._ensure():
            return
        try:
            current = self._client.status().get("repeat", "0")
            self._client.repeat(0 if current == "1" else 1)
        except Exception:
            self._connected = False

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
            )
            for s in songs
        ]

    def play_pos(self, pos: int) -> None:
        """Jump to and play the track at queue position ``pos``."""
        self._cmd(lambda: self._client.play(pos))

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

    def queue_add(self, paths: list[Path | str]) -> None:
        """Append tracks to the end of the queue."""
        if not self._ensure():
            return
        try:
            for p in paths:
                self._client.add(self._to_relative(Path(p)))
        except Exception:
            self._connected = False

    def remove_pos(self, pos: int) -> None:
        """Remove the track at queue position ``pos``."""
        self._cmd(lambda: self._client.delete(pos))

    def move(self, from_pos: int, to_pos: int) -> None:
        """Reorder: move a queued track from one position to another."""
        if from_pos == to_pos:
            return
        self._cmd(lambda: self._client.move(from_pos, to_pos))

    # ── play history ──────────────────────────────────────────────────────────

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

    def _cmd(self, fn) -> None:
        if not self._ensure():
            return
        try:
            fn()
        except Exception:
            self._connected = False
