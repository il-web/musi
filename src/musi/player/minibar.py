"""Shared mini now-playing bar — the bottom 44px of most screens.

Drawn by the launcher and every app screen except Now Playing (which would be
mirroring itself) and the Search tab (whose keyboard docks over these pixels).
Always drawn, even with nothing playing, so content geometry never shifts.

Surface caches are module-level, like statusbar.py: every screen that draws the
bar shares one art load and one pair of text surfaces.
"""
from __future__ import annotations

import pygame

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
_prev_title:  str = ""
_prev_meta:   str = ""


def draw(surface: pygame.Surface, app, status) -> None:
    """Draw the bar at BAR_Y. Call after the screen's own content."""
    _reload_art(app, status)
    _update_text(status)

    pygame.draw.rect(surface, theme.CARD_BG, (0, BAR_Y, 320, BAR_H))
    pygame.draw.line(surface, (30, 30, 44), (0, BAR_Y), (320, BAR_Y), 1)

    if _art:
        surface.blit(_art, (8, BAR_Y + 6))
    else:
        pygame.draw.rect(surface, (40, 40, 55), (8, BAR_Y + 6, 32, 32),
                         border_radius=4)
        icons.draw_music_note(surface, 24, BAR_Y + 22, (80, 80, 100))

    if _title_surf:
        surface.blit(_title_surf, (48, BAR_Y + 8))
    if _meta_surf:
        surface.blit(_meta_surf, (48, BAR_Y + 25))

    col = _accent if status.state == "play" else (110, 110, 125)
    if status.state == "play":
        icons.draw_pause(surface, _CTRL_X + 12, BAR_Y + 22, col)
    else:
        icons.draw_play(surface, _CTRL_X + 12, BAR_Y + 22, col)


def hit(x: int, y: int) -> str | None:
    """Classify a tap: 'toggle' on the control, 'open' on the body, else None."""
    if y < BAR_Y:
        return None
    return "toggle" if x >= _CTRL_X else "open"


# ── internals ─────────────────────────────────────────────────────────────────

def _reload_art(app, status) -> None:
    global _art, _accent, _cached_path
    if status.path == _cached_path:
        return
    _cached_path = status.path
    _art, _accent = None, theme.ACCENT
    if not status.path or app.db is None:
        return
    res = art_cache.get_track_art_and_palette(
        app.db, status.path, status.artist, status.album)
    _art    = art_cache.load_surface(res["art_path"], (32, 32))
    _accent = art_cache.parse_palette(res["palette"], do_brighten=True)


def _update_text(status) -> None:
    global _title_surf, _meta_surf, _prev_title, _prev_meta
    title = status.title or "Nothing playing"
    meta  = status.artist or ""
    if title != _prev_title:
        _prev_title = title
        _title_surf = theme.render(title, 12, theme.WHITE, bold=True, max_width=224)
    if meta != _prev_meta:
        _prev_meta = meta
        _meta_surf = theme.render(meta, 10, theme.DIM, max_width=224)
