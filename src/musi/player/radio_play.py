"""Start a radio station from anywhere in the UI.

Tuning needs the network (TuneIn hands out a fresh stream address per play),
so it runs on a worker thread; the caller gets ``on_done(error_or_None)`` back
on that thread and should only set state that its draw() then acts on.
"""
from __future__ import annotations

import threading
from typing import Callable

from musi.library import radio, remote


def play_station(app, station: dict,
                 on_done: Callable[[str | None], None] | None = None) -> None:
    def work() -> None:
        error = None
        try:
            url = radio.stream_url(station)
            radio.note_playing(url, station)        # so the player can name it
            app.mpd.play_paths([url])
            radio.remember_stream(station, url)
            app.request_poll()
        except radio.RadioError as exc:
            error = str(exc)
        except Exception as exc:                    # MPD hiccup, bad URL…
            error = str(exc) or exc.__class__.__name__
        if on_done:
            on_done(error)

    threading.Thread(target=work, daemon=True).start()


def current_station(app) -> dict | None:
    path = app.status.path
    return radio.station_for(path) if remote.is_radio(path) else None


def step(app, direction: int,
         on_done: Callable[[str | None], None] | None = None) -> bool:
    """Next/previous saved station (radio has no track list to skip in).
    Returns False when there is nowhere to go."""
    stations = radio.saved()
    if not stations:
        return False
    cur = current_station(app)
    keys = [(s["provider"], s["id"]) for s in stations]
    here = (cur["provider"], cur["id"]) if cur else None
    i = keys.index(here) if here in keys else -1
    nxt = stations[(i + direction) % len(stations)]
    if cur and (nxt["provider"], nxt["id"]) == here:
        return False                                # the only saved station
    play_station(app, nxt, on_done)
    return True
