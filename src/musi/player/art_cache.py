"""Album art and palette cache."""

import json
from functools import lru_cache
from pathlib import Path

import pygame

from musi.player import theme


@lru_cache(maxsize=100)
def load_art_thumbnail(art_path: str, size: int = 46) -> pygame.Surface | None:
    """Load and scale a thumbnail with an LRU cache."""
    if not art_path or not Path(art_path).exists():
        return None
    try:
        img = pygame.image.load(art_path).convert()
        return pygame.transform.scale(img, (size, size))
    except Exception:
        return None


def get_track_art_and_palette(db, path: str, artist: str, album: str) -> dict:
    """Fetch art paths and palette for a track, trying exact path then artist/album."""
    if path:
        row = db.execute(
            """SELECT al.art_path, al.backdrop_path, al.palette
               FROM tracks t JOIN albums al ON al.id = t.album_id
               WHERE t.path = ?""",
            (path,),
        ).fetchone()
        if row:
            return dict(row)

    if artist and album:
        row = db.execute(
            """SELECT al.art_path, al.backdrop_path, al.palette
               FROM albums al JOIN artists ar ON ar.id = al.artist_id
               WHERE ar.name = ? AND al.title = ?""",
            (artist, album),
        ).fetchone()
        if row:
            return dict(row)
            
    return {"art_path": None, "backdrop_path": None, "palette": None}


def parse_palette(palette_json: str, do_brighten: bool = False) -> tuple:
    """Parse JSON palette and return the primary accent colour."""
    if not palette_json:
        return theme.ACCENT
    try:
        colours = json.loads(palette_json)
        if not colours:
            return theme.ACCENT
        accent = theme.hex_to_rgb(colours[0])
        if do_brighten:
            r, g, b = accent
            if r + g + b < 180:
                accent = theme.brighten(accent, 1.8)
        return accent
    except Exception:
        return theme.ACCENT


def load_surface(path: str, size: tuple[int, int]) -> pygame.Surface | None:
    """Load an image and scale it."""
    if not path or not Path(path).exists():
        return None
    try:
        img = pygame.image.load(path).convert()
        return pygame.transform.scale(img, size)
    except Exception:
        return None
