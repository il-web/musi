"""Shared mini now-playing bar — the bottom 44px of most screens.

Drawn by the launcher and every app screen except Now Playing (which would be
mirroring itself) and the Search tab (whose keyboard docks over these pixels).
Always drawn, even with nothing playing, so content geometry never shifts.

Surface caches are module-level, like statusbar.py: every screen that draws the
bar shares one art load and one pair of text surfaces.
"""
from __future__ import annotations

import pygame

import json
import time

from musi.library import radio, remote
from musi.player import art_cache, icons, theme

BAR_H: int = 44
BAR_Y: int = 480 - BAR_H          # 436
_CTRL_X: int = 280                # taps right of this hit the play/pause control

# ── module-level caches (shared across all screens) ───────────────────────────
_art:         pygame.Surface | None = None
_accent:      tuple = theme.ACCENT
_cached_path: str | None = "UNSET"
_title_surf:  pygame.Surface | None = None
_meta_surf:   pygame.Surface | None = None
_prev_title:  tuple = ("", False)   # (title, streamed?)
_prev_meta:   str = ""
_logo_retry:  float = 0.0     # radio: when to look for the logo again


def draw(surface: pygame.Surface, app, status, y: int = BAR_Y) -> None:
    """Draw the bar at ``y``. Call after the screen's own content.

    ``y`` defaults to BAR_Y so every existing caller is unaffected; the music
    app's dock passes DOCK_Y so the strip and the nav row read as one unit.
    """
    _reload_art(app, status)
    _update_text(status)

    pygame.draw.rect(surface, theme.CARD_BG, (0, y, 320, BAR_H))
    pygame.draw.line(surface, (30, 30, 44), (0, y), (320, y), 1)

    if _art:
        surface.blit(_art, (8, y + 6))
    else:
        pygame.draw.rect(surface, (40, 40, 55), (8, y + 6, 32, 32),
                         border_radius=4)
        icons.draw_music_note(surface, 24, y + 22, (80, 80, 100))

    if _title_surf:
        surface.blit(_title_surf, (48, y + 8))
    if _meta_surf:
        surface.blit(_meta_surf, (48, y + 25))

    col = _accent if status.state == "play" else (110, 110, 125)
    if status.state == "play":
        icons.draw_pause(surface, _CTRL_X + 12, y + 22, col)
    else:
        icons.draw_play(surface, _CTRL_X + 12, y + 22, col)


def hit(x: int, y: int, bar_y: int = BAR_Y) -> "str | None":
    """Classify a tap: 'toggle' on the control, 'open' on the body, else None."""
    if y < bar_y:
        return None
    return "toggle" if x >= _CTRL_X else "open"


# ── internals ─────────────────────────────────────────────────────────────────

def _reload_art(app, status) -> None:
    global _art, _accent, _cached_path, _logo_retry
    if status.path == _cached_path:
        if _logo_retry and time.monotonic() >= _logo_retry:
            if remote.kind(status.path) == "airplay":
                from musi.player import airplay
                _art = airplay.cover((32, 32))
                _logo_retry = time.monotonic() + 1.0 if _art is None else 0.0
            else:
                _radio_art(status.path)         # the logo may have landed
        return
    _cached_path = status.path
    _art, _accent = None, theme.ACCENT
    _logo_retry = 0.0
    if remote.is_radio(status.path):
        _radio_art(status.path)
        return
    if remote.kind(status.path) == "airplay":
        from musi.player import airplay
        _art = airplay.cover((32, 32))
        _logo_retry = time.monotonic() + 1.0 if _art is None else 0.0
        return
    if not status.path or app.db is None:
        return
    res = art_cache.get_track_art_and_palette(
        app.db, status.path, status.artist, status.album)
    _art    = art_cache.load_surface(res["art_path"], (32, 32))
    _accent = art_cache.parse_palette(res["palette"], do_brighten=True)


def _radio_art(path: str) -> None:
    """Station logo, once downloaded — checked at most once a second until
    then, so the render loop isn't stat()ing a file every frame."""
    global _art, _accent, _logo_retry
    st = radio.station_for(path)
    logo = radio.ensure_logo(st) if st else None
    if logo:
        _art = art_cache.load_surface(str(logo), (32, 32))
        palette = radio.logo_palette(st)
        if palette:
            _accent = art_cache.parse_palette(json.dumps(palette), do_brighten=True)
        _logo_retry = 0.0
    else:
        _logo_retry = time.monotonic() + 1.0 if st and st.get("image") else 0.0


def _update_text(status) -> None:
    global _title_surf, _meta_surf, _prev_title, _prev_meta
    title = status.title or "Nothing playing"
    meta  = status.artist or ""
    kind  = remote.kind(status.path)
    key   = (title, kind)
    if key != _prev_title:
        _prev_title = key
        tagged = kind in ("server", "radio", "airplay")
        _title_surf = theme.render(title, 12, theme.WHITE, bold=True,
                                   max_width=224 - (icons.CLOUD_W if tagged else 0))
        if kind == "server":
            _title_surf = icons.with_cloud(_title_surf, theme.DIM)
        elif kind == "radio":
            _title_surf = icons.with_radio(_title_surf, theme.DIM)
        elif kind == "airplay":
            _title_surf = icons.with_airplay(_title_surf, theme.DIM)
    if meta != _prev_meta:
        _prev_meta = meta
        _meta_surf = theme.render(meta, 10, theme.DIM, max_width=224)
