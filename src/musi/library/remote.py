"""Remote (server-streamed) tracks — how they are named everywhere in musi.

A track from a music server lives in the same ``tracks`` table as a local file,
with a URL in ``path`` instead of a filesystem path:

    http://127.0.0.1:8080/local/subsonic/stream/<song id>

That URL points at musi's own API service, which answers with a redirect to the
real server and fresh credentials (api/server.py). So the URL MPD keeps in its
queue, its state file and its stored playlists — and the one the database keeps
— never carries a password or token, and stays valid when the server's address
or the user's password changes.

Anything that would treat ``path`` as a file (the scanner, the artwork fetcher,
pathlib) has to ask is_remote() first. Note that ``Path(url)`` silently
corrupts a URL ("http://h/x" becomes "http:/h/x"), so never let one near it.
"""
from __future__ import annotations

from os import PathLike

STREAM_PREFIX = "http://127.0.0.1:8080/local/subsonic/stream/"


def is_remote(path: "str | PathLike | None") -> bool:
    return isinstance(path, str) and path.startswith(("http://", "https://"))


def stream_url(song_id: str) -> str:
    return STREAM_PREFIX + song_id


def song_id(path: "str | None") -> str | None:
    """The server's song id for one of our stream URLs, else None."""
    if isinstance(path, str) and path.startswith(STREAM_PREFIX):
        return path[len(STREAM_PREFIX):] or None
    return None


def kind(path: "str | None") -> str:
    """'server' (a music-server song), 'radio' (any other stream — musi only
    hands MPD other URLs for internet radio), or 'local'."""
    if not is_remote(path):
        return "local"
    return "server" if path.startswith(STREAM_PREFIX) else "radio"


def is_server(path: "str | None") -> bool:
    return kind(path) == "server"


def is_radio(path: "str | None") -> bool:
    return kind(path) == "radio"
