"""The launcher's first page — a big clock, "Continue listening", and info.

Drawn by LauncherScreen as page 0 (key "home"), so musi opens on it. Like
the app pages it is rendered once into a cached surface and only rebuilt
when what it shows changes (the minute, the song, play state, the info
line) — see signature().

The page is a per-pixel-alpha surface (the wallpaper shows through), so
everything blitted onto it goes through blit.onto at even columns.
"""
from __future__ import annotations

from datetime import datetime

import pygame

from musi.player import art_cache, blit, icons, theme

CLOCK_Y = 26
DATE_Y  = 124
SOFT    = (225, 225, 235)        # date: readable over a bright wallpaper
CARD    = pygame.Rect(16, 168, 288, 100)
ART     = 76
PLAY_C  = (CARD.right - 34, CARD.centery)
INFO_Y  = 290


# ── data (SQL — never from draw; the launcher calls it on enter / track change)

def continue_item(db) -> dict | None:
    """The most recently played track, with what the card needs."""
    if db is None:
        return None
    row = db.execute(
        """SELECT t.path, t.title, t.album_id, ar.name AS artist, al.art_path
           FROM play_history h JOIN tracks t ON t.id = h.track_id
           JOIN artists ar ON ar.id = t.artist_id
           JOIN albums al ON al.id = t.album_id
           ORDER BY h.played_at DESC, h.id DESC LIMIT 1""").fetchone()
    return dict(row) if row else None


def info_line(db) -> str:
    """'21 albums · 1834 songs on Navidrome' — counted once per refresh."""
    parts = []
    if db is not None:
        n = db.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
        parts.append(f"{n} album" + ("" if n == 1 else "s"))
    try:
        from musi.library import subsonic
        s = subsonic.load_settings()
        if s and s.get("track_count"):
            parts.append(f"{s['track_count']} songs on your server")
    except Exception:
        pass
    return "  ·  ".join(parts)


def signature(now: datetime, item: dict | None, status, info: str,
              extra: str) -> str:
    """Everything the page shows — the launcher rebuilds it when this changes."""
    from musi.player.screens.clock import format_now
    playing = _playing(item, status)
    return "|".join([format_now(now)[0], (item or {}).get("path", ""),
                     str(playing), info, extra])


# ── drawing ──────────────────────────────────────────────────────────────────

def render(now: datetime, item: dict | None, status, info: str, extra: str,
           size: tuple[int, int]) -> pygame.Surface:
    from musi.player.screens.clock import format_now
    page = pygame.Surface(size, pygame.SRCALPHA)
    hhmm, date = format_now(now)

    clock = theme.render(hhmm, 66, theme.WHITE, bold=True)
    blit.onto(page, clock, clock.get_rect(centerx=160, y=CLOCK_Y))
    d = theme.render(date, 12, SOFT, bold=True)
    blit.onto(page, d, d.get_rect(centerx=160, y=DATE_Y))

    # Continue listening
    pygame.draw.rect(page, theme.CARD_BG, CARD, border_radius=16)
    ax, ay = CARD.x + 12, CARD.centery - ART // 2
    art = art_cache.load_art_thumbnail((item or {}).get("art_path") or "", ART) if item else None
    if art is not None:
        blit.onto(page, art, (ax, ay))
    else:
        pygame.draw.rect(page, (44, 44, 60), (ax, ay, ART, ART), border_radius=8)
        icons.draw_music_note(page, ax + ART // 2, ay + ART // 2, (110, 110, 130))
    tx = ax + ART + 14
    label = "Continue listening" if item else "Start listening"
    blit.onto(page, theme.render(label.upper(), 9, theme.DIM, bold=True), (tx, CARD.y + 20))
    title = (item or {}).get("title") or "Open Music"
    blit.onto(page, theme.render(title, 15, theme.WHITE, bold=True, max_width=128),
              (tx, CARD.y + 38))
    if item:
        blit.onto(page, theme.render(item.get("artist", ""), 11, theme.DIM, max_width=128),
                  (tx, CARD.y + 60))
    playing = _playing(item, status)
    pygame.draw.circle(page, theme.ACCENT, PLAY_C, 20)
    if playing:
        icons.draw_pause(page, PLAY_C[0], PLAY_C[1], theme.WHITE, size="sm")
    else:
        icons.draw_play(page, PLAY_C[0] + 1, PLAY_C[1], theme.WHITE, size="sm")

    # info, on a dark strip so it reads over any wallpaper
    lines = [theme.render(t, 11, SOFT, max_width=268) for t in (info, extra) if t]
    if lines:
        w = max(l.get_width() for l in lines) + 28
        h = 20 * len(lines) + 12
        pygame.draw.rect(page, theme.CARD_BG, ((320 - w) // 2 & ~1, INFO_Y - 6, w, h),
                         border_radius=12)
        y = INFO_Y
        for line in lines:
            blit.onto(page, line, line.get_rect(centerx=160, y=y))
            y += 20
    return page


def _playing(item: dict | None, status) -> bool:
    return (bool(item) and getattr(status, "path", None) == item["path"]
            and getattr(status, "state", "") == "play")


def hit(x: int, y: int) -> str | None:
    """'play' on the round button, 'card' on the rest of the card."""
    if (x - PLAY_C[0]) ** 2 + (y - PLAY_C[1]) ** 2 <= 26 ** 2:
        return "play"
    if CARD.collidepoint(x, y):
        return "card"
    return None


# ── actions ──────────────────────────────────────────────────────────────────

def resume(app, item: dict | None, open_player: bool) -> None:
    """Carry on: if that song is what MPD has, just play/pause it; otherwise
    play its album from that song. With no history, open Music."""
    if item is None:
        from musi.player.screens.music import MusicHostScreen
        app.push(MusicHostScreen(app))
        return
    status = getattr(app, "status", None)
    if getattr(status, "path", None) == item["path"]:
        if status.state != "play" or not open_player:
            app.toggle_play()
    else:
        rows = app.db.execute(
            "SELECT path FROM tracks WHERE album_id = ? ORDER BY disc_number, track_number, title",
            (item["album_id"],)).fetchall()
        paths = [r[0] for r in rows]
        start = paths.index(item["path"]) if item["path"] in paths else 0
        app.mpd.play_paths(paths or [item["path"]], start_index=start)
        app.request_poll()
    if open_player:
        from musi.player.screens.now_playing import NowPlayingScreen
        app.push(NowPlayingScreen(app))
