"""Decides when a play counts as a listen, and tells whoever wants to know.

Fed the polled PlayerStatus about once a second. It measures time actually
spent playing (pauses don't count, seeking doesn't count) and, when a track
ends or is skipped, applies the ListenBrainz/Last.fm rule: a listen is half
the track or four minutes, whichever comes first, and tracks under 30 s
don't count at all.

Internet radio is ignored: you didn't pick those songs.

Two receivers today:
  - ListenBrainz (if signed in): 'playing now' at the start, the listen at
    the end — queued, so offline plays go out later.
  - The music server (server tracks only): Subsonic 'now playing' at the
    start, the real scrobble at the end — so Navidrome's play counts follow
    the same rule instead of counting every skip.
"""
from __future__ import annotations

import logging
import time

from musi.library import remote

MIN_TRACK_S = 30
MAX_NEEDED_S = 240


def qualifies(played_s: float, duration_s: float) -> bool:
    if duration_s and duration_s < MIN_TRACK_S:
        return False
    needed = min(MAX_NEEDED_S, duration_s / 2) if duration_s else MAX_NEEDED_S
    return played_s >= needed


class Scrobbler:
    def __init__(self, on_start=None, on_listen=None) -> None:
        # on_start(meta) when a track starts playing; on_listen(meta, started_at)
        # when it finished and qualified. Defaults: ListenBrainz + server.
        self._on_start = on_start or _default_start
        self._on_listen = on_listen or _default_listen
        self._cur: dict | None = None     # meta of the track being measured
        self._played = 0.0
        self._started_at = 0.0            # wall clock, for listened_at
        self._last_t: float | None = None
        self._last_elapsed = 0.0

    def update(self, status, now: float | None = None, wall: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        path = status.path if getattr(status, "connected", True) else None
        if remote.is_radio(path):
            path = None         # radio never counts as a listen (by choice)
        playing = status.state == "play" and bool(path)
        elapsed = float(getattr(status, "elapsed", 0.0) or 0.0)

        # same file again from the top (repeat-one, replay) is a new play
        replay = (self._cur is not None and path == self._cur["path"]
                  and elapsed + 5 < self._last_elapsed and elapsed < 5)
        if self._cur is not None and (path != self._cur["path"] or replay):
            self._finish()
        if self._cur is None and playing:
            self._begin(status, wall)

        if self._cur is not None and playing and self._last_t is not None:
            # wall time between polls, capped so a suspended loop can't
            # credit a minute of "listening" in one step
            self._played += min(max(0.0, now - self._last_t), 5.0)
        self._last_t = now
        self._last_elapsed = elapsed

    def _begin(self, status, wall: float) -> None:
        self._cur = {"path": status.path, "title": status.title,
                     "artist": status.artist, "album": status.album,
                     "duration": float(status.duration or 0)}
        self._played = 0.0
        self._started_at = wall
        _safe(self._on_start, self._cur)

    def _finish(self) -> None:
        cur, self._cur = self._cur, None
        if cur and qualifies(self._played, cur["duration"]):
            _safe(self._on_listen, cur, self._started_at)


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        logging.warning("scrobble receiver failed", exc_info=True)


def _default_start(meta: dict) -> None:
    from musi.library import listenbrainz, remote, subsonic
    listenbrainz.playing_now(meta)
    if remote.is_server(meta["path"]):
        subsonic.scrobble_async(meta["path"], submission=False)


def _default_listen(meta: dict, started_at: float) -> None:
    from musi.library import listenbrainz, remote, subsonic
    listenbrainz.record_listen(meta, started_at)
    if remote.is_server(meta["path"]):
        subsonic.scrobble_async(meta["path"], submission=True)
