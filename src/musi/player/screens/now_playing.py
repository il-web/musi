"""Now Playing screen — full-art backdrop with transport controls."""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

# Layout — 320×480 panel (art + transport + secondary row + volume)
ART_W, ART_H = 220, 220
ART_X = (320 - ART_W) // 2   # centred → 50
ART_Y = 32
INFO_Y   = ART_Y + ART_H + 12   # 264 title
ARTIST_Y = INFO_Y + 26          # 290 artist
BAR_Y    = ARTIST_Y + 28        # 318 progress bar
TIME_Y   = BAR_Y + 10           # 328 time
CTRL_Y   = TIME_Y + 38          # 366 transport row
SEC_Y    = CTRL_Y + 40          # 406 shuffle/repeat/queue row
VOL_Y    = SEC_Y + 34           # 440 volume slider
VOL_X    = 40                   # slider left edge
VOL_W    = 224                  # slider width (40 → 264)


class NowPlayingScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)

        # art / palette (reload on track change)
        self._backdrop: pygame.Surface | None = None
        self._art:      pygame.Surface | None = None
        self._accent:   tuple = theme.ACCENT
        self._cached_path: str | None = "UNSET"

        # cached text surfaces — only re-render when content changes
        self._title_surf:  pygame.Surface | None = None
        self._meta_surf:   pygame.Surface | None = None
        self._time_surf:   pygame.Surface | None = None
        self._state_cache: str = ""
        self._shuffle_cache: bool | None = None
        self._repeat_cache:  bool | None = None

        self._prev_title:   str = ""
        self._prev_meta:    str = ""
        self._prev_elapsed: int = -1   # whole seconds

        # volume drag + static surfaces (built on first draw, after pygame.init)
        self._drag_vol:   int | None = None              # live value while dragging
        self._queue_lbl:  pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._reload_art(self.app.status)

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        # build static surfaces once, after pygame.init()
        if self._queue_lbl is None:
            self._queue_lbl = theme.render("Queue", 10, theme.WHITE)

        self._reload_art(status)
        self._update_text_cache(status)

        # 1 — background (backdrop or solid)
        if self._backdrop:
            surface.blit(self._backdrop, (0, 0))
        else:
            surface.fill(theme.BG)

        # 2 — status bar
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        # 3 — album art thumbnail
        art_rect = pygame.Rect(ART_X, ART_Y, ART_W, ART_H)
        if self._art:
            surface.blit(self._art, (ART_X, ART_Y))
            pygame.draw.rect(surface, self._accent, art_rect, 2, border_radius=4)
        else:
            pygame.draw.rect(surface, theme.CARD_BG, art_rect, border_radius=4)
            lbl = theme.render("no track", 13, theme.DIM)
            surface.blit(lbl, lbl.get_rect(center=art_rect.center))

        # 5 — track title + artist (shadow then text for readability)
        if self._title_surf:
            r = self._title_surf.get_rect(centerx=160, y=INFO_Y)
            _shadow(surface, self._title_surf, r.x, r.y)
            surface.blit(self._title_surf, r)
        if self._meta_surf:
            r = self._meta_surf.get_rect(centerx=160, y=ARTIST_Y)
            _shadow(surface, self._meta_surf, r.x, r.y)
            surface.blit(self._meta_surf, r)

        # 6 — progress bar
        _draw_bar(surface, 16, BAR_Y, 288, 5, status.progress, self._accent)

        # 7 — time
        if self._time_surf:
            _shadow(surface, self._time_surf, 16, TIME_Y)
            surface.blit(self._time_surf, (16, TIME_Y))

        # 8 — transport controls
        _draw_prev(surface,  76, CTRL_Y, theme.WHITE)
        _draw_play_pause(surface, 160, CTRL_Y, status.state == "play", self._accent)
        _draw_next(surface, 244, CTRL_Y, theme.WHITE)

        # 9 — shuffle / repeat toggles + queue button
        off = (150, 150, 165)
        _draw_shuffle(surface, 56,  SEC_Y, self._accent if status.shuffle else off)
        _draw_repeat(surface,  120, SEC_Y, self._accent if status.repeat  else off)
        _draw_list_icon(surface, 232, SEC_Y, theme.WHITE)
        surface.blit(self._queue_lbl, self._queue_lbl.get_rect(midleft=(246, SEC_Y)))

        # 10 — volume slider
        vol = self._drag_vol if self._drag_vol is not None else status.volume
        _draw_volume(surface, VOL_X, VOL_W, VOL_Y, vol, self._accent)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.BACK
        # transport row
        if CTRL_Y - 22 <= y <= CTRL_Y + 22:
            if x < 120:
                return Button.PREV
            elif x <= 200:
                return Button.PLAY_PAUSE
            else:
                return Button.NEXT
        # secondary row: shuffle | repeat | queue
        if SEC_Y - 18 <= y <= SEC_Y + 18:
            if x < 90:
                self.app.mpd.toggle_shuffle()
            elif x < 160:
                self.app.mpd.toggle_repeat()
            elif x > 200:
                self._open_queue()
            return None
        # tapping the album art toggles play/pause (big target)
        if ART_Y <= y <= ART_Y + ART_H:
            return Button.PLAY_PAUSE
        return None

    # ── volume slider (drag gesture) ────────────────────────────────────────────

    def on_press(self, x: int, y: int) -> bool:
        if VOL_Y - 16 <= y <= VOL_Y + 16 and VOL_X - 14 <= x <= VOL_X + VOL_W + 14:
            self._set_vol_from_x(x)
            return True
        return False

    def on_drag(self, x: int, y: int) -> None:
        self._set_vol_from_x(x)

    def on_release(self, x: int, y: int) -> None:
        self._drag_vol = None

    def _set_vol_from_x(self, x: int) -> None:
        vol = max(0, min(100, round((x - VOL_X) / VOL_W * 100)))
        self._drag_vol = vol
        self.app.mpd.set_volume(vol)

    def _open_queue(self) -> None:
        from musi.player.screens.queue import QueueScreen
        self.app.push(QueueScreen(self.app))

    def handle(self, button: Button, status: PlayerStatus) -> None:
        mpd = self.app.mpd
        if   button == Button.PLAY_PAUSE: mpd.play_pause()
        elif button == Button.NEXT:       mpd.next_track()
        elif button == Button.PREV:       mpd.prev_track()
        elif button == Button.VOL_UP:     mpd.set_volume(min(100, status.volume + 5))
        elif button == Button.VOL_DOWN:   mpd.set_volume(max(0,   status.volume - 5))
        elif button == Button.BACK:       self.app.pop()

    # ── internal ──────────────────────────────────────────────────────────────

    def _reload_art(self, status: PlayerStatus) -> None:
        if status.path == self._cached_path:
            return
        self._cached_path = status.path
        self._backdrop    = None
        self._art         = None
        self._accent      = theme.ACCENT

        if not status.path:
            return

        # Try exact path match first
        row = self.app.db.execute(
            """SELECT al.art_path, al.backdrop_path, al.palette
               FROM tracks t JOIN albums al ON al.id = t.album_id
               WHERE t.path = ?""",
            (status.path,),
        ).fetchone()

        # Fallback: match by artist + album name from MPD tags
        # (handles OGG/MP3 test files whose FLAC originals are in the DB)
        if not row and status.artist and status.album:
            row = self.app.db.execute(
                """SELECT al.art_path, al.backdrop_path, al.palette
                   FROM albums al
                   JOIN artists ar ON ar.id = al.artist_id
                   WHERE ar.name = ? AND al.title = ?""",
                (status.artist, status.album),
            ).fetchone()

        if not row:
            return

        if row["backdrop_path"] and Path(row["backdrop_path"]).exists():
            try:
                _bd = pygame.image.load(row["backdrop_path"]).convert()
                self._backdrop = pygame.transform.scale(_bd, (320, 480))
            except Exception:
                pass

        if row["art_path"] and Path(row["art_path"]).exists():
            try:
                img = pygame.image.load(row["art_path"]).convert()
                self._art = pygame.transform.scale(img, (ART_W, ART_H))
            except Exception:
                pass

        if row["palette"]:
            try:
                colours = json.loads(row["palette"])
                if colours:
                    self._accent = theme.hex_to_rgb(colours[0])
            except Exception:
                pass

    def _update_text_cache(self, status: PlayerStatus) -> None:
        """Re-render text surfaces only when content changes."""
        title = status.title or "musi"
        meta  = f"{status.artist}" + (f"  ·  {status.album}" if status.album else "")

        if title != self._prev_title:
            self._prev_title  = title
            self._title_surf  = theme.render(title, 18, theme.WHITE, bold=True, max_width=296)

        if meta != self._prev_meta:
            self._prev_meta  = meta
            self._meta_surf  = theme.render(meta, 13, theme.WHITE, max_width=296)

        elapsed_s = int(status.elapsed)
        if elapsed_s != self._prev_elapsed:
            self._prev_elapsed = elapsed_s
            t = f"{_fmt(status.elapsed)}  /  {_fmt(status.duration)}"
            self._time_surf = theme.render(t, 11, theme.WHITE)


# ── drawing helpers ───────────────────────────────────────────────────────────

def _shadow(surface: pygame.Surface, surf: pygame.Surface, x: int, y: int, offset: int = 2) -> None:
    """Blit a dark copy of surf offset by `offset` pixels for a drop shadow."""
    shadow = surf.copy()
    shadow.fill((0, 0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(shadow, (x + offset, y + offset))


# ── drawing primitives ────────────────────────────────────────────────────────

def _draw_bar(surface, x, y, w, h, progress, colour):
    pygame.draw.rect(surface, (40, 40, 50), (x, y, w, h), border_radius=h)
    if progress > 0:
        pygame.draw.rect(surface, colour, (x, y, max(h, int(w * progress)), h), border_radius=h)


def _draw_play_pause(surface, cx, cy, playing, colour):
    if playing:
        pygame.draw.rect(surface, colour, (cx - 9, cy - 11, 6, 22), border_radius=2)
        pygame.draw.rect(surface, colour, (cx + 3, cy - 11, 6, 22), border_radius=2)
    else:
        pygame.draw.polygon(surface, colour, [(cx - 9, cy - 13), (cx - 9, cy + 13), (cx + 13, cy)])


def _draw_prev(surface, cx, cy, colour):
    pygame.draw.rect(surface, colour, (cx - 13, cy - 11, 4, 22), border_radius=1)
    pygame.draw.polygon(surface, colour, [(cx - 9, cy), (cx + 9, cy - 11), (cx + 9, cy + 11)])


def _draw_next(surface, cx, cy, colour):
    pygame.draw.rect(surface, colour, (cx + 9, cy - 11, 4, 22), border_radius=1)
    pygame.draw.polygon(surface, colour, [(cx + 5, cy), (cx - 13, cy - 11), (cx - 13, cy + 11)])


def _fmt(secs: float) -> str:
    s = max(0, int(secs))
    return f"{s // 60}:{s % 60:02d}"


def _draw_shuffle(surface, cx, cy, col):
    pygame.draw.line(surface, col, (cx - 11, cy - 5), (cx + 11, cy + 5), 2)
    pygame.draw.line(surface, col, (cx - 11, cy + 5), (cx + 11, cy - 5), 2)
    pygame.draw.polygon(surface, col, [(cx + 11, cy - 5), (cx + 4, cy - 6), (cx + 6, cy - 1)])
    pygame.draw.polygon(surface, col, [(cx + 11, cy + 5), (cx + 4, cy + 6), (cx + 6, cy + 1)])


def _draw_repeat(surface, cx, cy, col):
    pygame.draw.rect(surface, col, pygame.Rect(cx - 10, cy - 7, 20, 14), 2, border_radius=6)
    pygame.draw.polygon(surface, col, [(cx + 3, cy - 7), (cx + 11, cy - 7), (cx + 7, cy - 2)])


def _draw_list_icon(surface, cx, cy, col):
    for dy in (-6, 0, 6):
        pygame.draw.line(surface, col, (cx - 9, cy + dy), (cx + 9, cy + dy), 2)


def _speaker_icon(surface, cx, cy, col):
    pygame.draw.polygon(surface, col, [
        (cx - 6, cy - 3), (cx - 2, cy - 3), (cx + 2, cy - 7),
        (cx + 2, cy + 7), (cx - 2, cy + 3), (cx - 6, cy + 3),
    ])
    pygame.draw.arc(surface, col, pygame.Rect(cx + 2, cy - 7, 9, 14), -0.9, 0.9, 2)


def _draw_volume(surface, x, w, y, vol, accent):
    _speaker_icon(surface, 18, y, (205, 205, 215))
    pygame.draw.rect(surface, (60, 60, 78), (x, y - 2, w, 4), border_radius=2)
    fill = int(w * max(0, min(100, vol)) / 100)
    if fill > 0:
        pygame.draw.rect(surface, accent, (x, y - 2, fill, 4), border_radius=2)
    pygame.draw.circle(surface, theme.WHITE, (x + fill, y), 6)
    pct = theme.render(f"{int(vol)}%", 10, theme.WHITE)
    surface.blit(pct, pct.get_rect(midleft=(x + w + 10, y)))
