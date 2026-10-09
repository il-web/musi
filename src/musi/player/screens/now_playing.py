"""Now Playing screen — edge-to-edge art hero over a solid control panel."""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from musi.player import art_cache, audio_detect, icons, motion, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

# Layout — 320×480 hero: art bleeds from the top edge into a solid panel.
# Art area is 320×252 (1.7× the old 220×220 card) and every control today's
# screen had still fits: shuffle | repeat | lyrics | Queue, plus the volume
# slider. Do not trade the slider for an icon — this device has no hardware
# volume control.
ART_BLEED_H = 252               # art runs 0..252, full width
FADE_H      = 70                # art dissolves into the panel over this span

INFO_Y   = 258                  # title
ARTIST_Y = 282                  # artist · album
BAR_Y    = 312                  # progress bar
BAR_X    = 16
BAR_W    = 288
TIME_Y   = BAR_Y + 10           # 322
CTRL_Y   = 362                  # transport row
SEC_Y    = 412                  # shuffle / repeat / lyrics / queue
VOL_Y    = 452                  # volume slider
VOL_X    = 40
VOL_W    = 224

# Motion — all of it switches off with Customization → Animations.
SWAP_S    = 0.35                # track change: art cross-fade + text slide
SWAP_PX   = 28                  # how far the title/artist slide
PP_POP_S  = 0.25                # play ⇄ pause icon pops in
RIPPLE_S  = 0.35                # soft disc behind a tapped control
HEART_S   = 0.32                # favourite heart bump


class NowPlayingScreen(Screen):
    # Stay visible while listening: dim only after 15 min, screen off a
    # minute after that (other screens use the much shorter global defaults).
    dim_after = 15 * 60
    off_after = 16 * 60
    transition = "sheet"        # rises out of the mini bar, drops back into it

    def __init__(self, app) -> None:
        super().__init__(app)

        # art / palette (reload on track change)
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

        # favourite state for the current track (a heart in the secondary row)
        self._fav:      bool = False
        self._fav_path: str | None = "UNSET"

        self._prev_title:   str = ""
        self._prev_meta:    str = ""
        self._prev_elapsed: int = -1   # whole seconds

        # volume / seek drag + static surfaces (built on first draw, after pygame.init)
        self._drag_vol:   int   | None = None            # live value while dragging
        self._drag_seek:  float | None = None            # 0.0–1.0 while scrubbing
        self._queue_lbl:  pygame.Surface | None = None

        # motion state
        self._swap       = motion.Tween(SWAP_S)
        self._swap_dir   = 1                            # +1 next, -1 previous
        self._next_dir   = 1                            # set by NEXT/PREV taps
        self._old_art:   pygame.Surface | None = None
        self._old_accent: tuple = theme.ACCENT
        self._old_title: pygame.Surface | None = None
        self._old_meta:  pygame.Surface | None = None
        self._pp_pop     = motion.Tween(PP_POP_S)
        self._pp_state:  str | None = None
        self._ripple     = motion.Tween(RIPPLE_S)
        self._ripple_at: tuple[int, int] = (0, 0)
        self._heart      = motion.Tween(HEART_S)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._reload_art(self.app.status)

    @property
    def animates(self) -> bool:
        return (self._swap.active() or self._pp_pop.active()
                or self._ripple.active() or self._heart.active())

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        # build static surfaces once, after pygame.init()
        if self._queue_lbl is None:
            self._queue_lbl = theme.render("Queue", 10, theme.WHITE)

        self._reload_art(status)
        self._reload_fav(status)
        self._update_text_cache(status)

        swap = self._swap.progress()
        swap_e = motion.ease_out_cubic(swap)
        accent = (motion.lerp_colour(self._old_accent, self._accent, swap_e)
                  if swap < 1 else self._accent)

        # 1 — art bleeding from the top edge, dissolving into the panel;
        #     on a track change the new art fades in over the old
        surface.fill(theme.BG)
        if swap < 1:
            _draw_art(surface, self._old_art, 1.0)
            _draw_art(surface, self._art, swap_e)
        else:
            _draw_art(surface, self._art, 1.0)

        fade = pygame.Surface((320, FADE_H), pygame.SRCALPHA)
        for i in range(FADE_H):
            fade.fill((10, 10, 15, int(255 * (i / FADE_H) ** 1.6)),
                      (0, i, 320, 1))
        surface.blit(fade, (0, ART_BLEED_H - FADE_H))
        pygame.draw.rect(surface, theme.BG,
                         (0, ART_BLEED_H, 320, 480 - ART_BLEED_H))

        # 2 — status bar on a solid band; the art washed the clock out
        pygame.draw.rect(surface, (8, 8, 13), (0, 0, 320, 26))
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)

        # 5 — track title + artist (shadow then text for readability);
        #     on a track change the old text slides out as the new slides in
        #     — handed over, not cross-faded: two titles on top of each
        #     other are unreadable, so the old one is gone before the new
        #     one shows (out over the first 40%, in over the last 60%)
        if swap < 1:
            out_p = motion.ease_out_cubic(swap / 0.4)
            in_p  = motion.ease_out_cubic((swap - 0.4) / 0.6)
            out_dx = int(-self._swap_dir * SWAP_PX * out_p)
            in_dx  = int(self._swap_dir * SWAP_PX * (1 - in_p))
            _text(surface, self._old_title,  INFO_Y,   out_dx, 1 - out_p)
            _text(surface, self._old_meta,   ARTIST_Y, out_dx, 1 - out_p)
            _text(surface, self._title_surf, INFO_Y,   in_dx, in_p)
            _text(surface, self._meta_surf,  ARTIST_Y, in_dx, in_p)
        else:
            _text(surface, self._title_surf, INFO_Y,   0, 1.0)
            _text(surface, self._meta_surf,  ARTIST_Y, 0, 1.0)

        # 6 — progress bar (scrub preview while dragging)
        progress = self._drag_seek if self._drag_seek is not None else status.progress
        _draw_bar(surface, BAR_X, BAR_Y, BAR_W, 5, progress, accent)
        if self._drag_seek is not None:
            knob_x = BAR_X + int(BAR_W * self._drag_seek)
            pygame.draw.circle(surface, theme.WHITE, (knob_x, BAR_Y + 2), 7)

        # 7 — time (target time while scrubbing)
        if self._drag_seek is not None and status.duration > 0:
            t  = f"{_fmt(self._drag_seek * status.duration)}  /  {_fmt(status.duration)}"
            ts = theme.render(t, 11, theme.WHITE)
            _shadow(surface, ts, 16, TIME_Y)
            surface.blit(ts, (16, TIME_Y))
        elif self._time_surf:
            _shadow(surface, self._time_surf, 16, TIME_Y)
            surface.blit(self._time_surf, (16, TIME_Y))

        # 8 — transport controls (ripple behind whichever was tapped; the
        #     play/pause glyph pops in whenever the state flips)
        if self._ripple.active():
            _draw_ripple(surface, self._ripple_at, self._ripple.progress(), accent)
        _draw_prev(surface, 76, CTRL_Y, theme.WHITE)
        if self._pp_state is not None and self._pp_state != status.state:
            self._pp_pop.start()
        self._pp_state = status.state
        pop = motion.ease_out_back(self._pp_pop.progress())
        _draw_play_pause(surface, status.state == "play", accent,
                         motion.lerp(0.6, 1.0, pop))
        _draw_next(surface, 244, CTRL_Y, theme.WHITE)

        # 9 — favourite / shuffle / repeat / lyrics toggles + queue button
        off = (150, 150, 165)
        _draw_heart(surface, 34, SEC_Y, accent if self._fav else off, self._fav,
                    1 + 0.45 * motion.bump(self._heart.progress()))
        _draw_shuffle(surface, 76,  SEC_Y, accent if status.shuffle else off)
        _draw_repeat(surface,  118, SEC_Y, accent if status.repeat  else off)
        _draw_lyrics_icon(surface, 160, SEC_Y,
                          theme.WHITE if status.path else off)
        _draw_list_icon(surface, 202, SEC_Y, theme.WHITE)
        surface.blit(self._queue_lbl, self._queue_lbl.get_rect(midleft=(214, SEC_Y)))

        # 10 — volume slider
        vol = self._drag_vol if self._drag_vol is not None else status.volume
        _draw_volume(surface, VOL_X, VOL_W, VOL_Y, vol, accent)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.HOME
        # transport row
        if CTRL_Y - 22 <= y <= CTRL_Y + 22:
            if x < 120:
                return Button.PREV
            elif x <= 200:
                return Button.PLAY_PAUSE
            else:
                return Button.NEXT
        # secondary row: favourite | shuffle | repeat | lyrics | queue
        if SEC_Y - 18 <= y <= SEC_Y + 18:
            if x < 139:     # the three toggles answer with a ripple
                self._start_ripple(34 if x < 55 else 76 if x < 97 else 118, SEC_Y)
            if x < 55:
                self._toggle_favorite()
            elif x < 97:
                self.app.mpd.toggle_shuffle()
                self.app.request_poll()
            elif x < 139:
                self.app.mpd.toggle_repeat()
                self.app.request_poll()
            elif x < 181:
                self._open_lyrics()
            else:
                self._open_queue()
            return None
        # tapping the album art toggles play/pause (big target)
        if 26 <= y <= ART_BLEED_H:
            return Button.PLAY_PAUSE
        return None

    # ── volume slider + seek bar (drag gestures) ────────────────────────────────

    def on_press(self, x: int, y: int) -> bool:
        # seek: grab anywhere on/near the progress bar (tap or scrub)
        if BAR_Y - 14 <= y <= BAR_Y + 16 and BAR_X - 10 <= x <= BAR_X + BAR_W + 10:
            if self.app.status.duration > 0:
                self._drag_seek = self._seek_frac_from_x(x)
                return True
            return False
        if VOL_Y - 16 <= y <= VOL_Y + 16 and VOL_X - 14 <= x <= VOL_X + VOL_W + 14:
            self._set_vol_from_x(x)
            return True
        return False

    def on_drag(self, x: int, y: int) -> None:
        if self._drag_seek is not None:
            self._drag_seek = self._seek_frac_from_x(x)
        else:
            self._set_vol_from_x(x)

    def on_release(self, x: int, y: int) -> None:
        if self._drag_seek is not None:
            duration = self.app.status.duration
            if duration > 0:
                self.app.mpd.seek(self._drag_seek * duration)
            self._drag_seek = None
        self._drag_vol = None
        self.app.request_poll()

    def _seek_frac_from_x(self, x: int) -> float:
        return max(0.0, min(1.0, (x - BAR_X) / BAR_W))

    def _set_vol_from_x(self, x: int) -> None:
        vol = max(0, min(100, round((x - VOL_X) / VOL_W * 100)))
        if vol != self._drag_vol:
            self._drag_vol = vol
            self.app.mpd.set_volume(vol)

    def _open_queue(self) -> None:
        from musi.player.screens.queue import QueueScreen
        self.app.push(QueueScreen(self.app))

    def _toggle_favorite(self) -> None:
        """Add/remove the current track in the Favourites playlist."""
        path = self.app.status.path
        if not path:
            return
        self._fav = self.app.mpd.toggle_favorite(path)
        self._fav_path = path
        if self._fav:
            self._heart.start()

    def _start_ripple(self, cx: int, cy: int) -> None:
        self._ripple_at = (cx, cy)
        self._ripple.start()

    def _open_lyrics(self) -> None:
        """Lyrics for whatever is playing right now — nothing without a track."""
        status = self.app.status
        if not status.path:
            return
        from musi.player.screens.lyrics import LyricsScreen
        self.app.push(LyricsScreen(self.app, status))

    def handle(self, button: Button, status: PlayerStatus) -> None:
        mpd = self.app.mpd
        if button in _TRANSPORT_X:
            self._start_ripple(_TRANSPORT_X[button], CTRL_Y)
        if button in (Button.NEXT, Button.PREV):
            self._next_dir = 1 if button == Button.NEXT else -1
        if   button == Button.PLAY_PAUSE: self.app.toggle_play()
        elif button == Button.NEXT:       mpd.next_track();  self.app.request_poll()
        elif button == Button.PREV:       mpd.prev_track();  self.app.request_poll()
        elif button == Button.VOL_UP:     mpd.set_volume(min(100, status.volume + 5)); self.app.request_poll()
        elif button == Button.VOL_DOWN:   mpd.set_volume(max(0,   status.volume - 5)); self.app.request_poll()
        elif button == Button.BACK:       self.app.pop()

    # ── internal ──────────────────────────────────────────────────────────────

    def _reload_art(self, status: PlayerStatus) -> None:
        if status.path == self._cached_path:
            return
        if self._cached_path != "UNSET":
            # a real track change, not the first frame: animate away from
            # what is showing now (direction from the NEXT/PREV tap, if any)
            self._old_art, self._old_accent = self._art, self._accent
            self._old_title, self._old_meta = self._title_surf, self._meta_surf
            self._swap_dir, self._next_dir = self._next_dir, 1
            self._swap.start()
        self._cached_path = status.path
        self._art         = None
        self._accent      = theme.ACCENT

        if not status.path or self.app.db is None:
            return

        res = art_cache.get_track_art_and_palette(self.app.db, status.path, status.artist, status.album)
        self._art = art_cache.load_surface(res["art_path"], (320, 320))
        self._accent = art_cache.parse_palette(res["palette"])

    def _reload_fav(self, status: PlayerStatus) -> None:
        """Refresh the heart state when the track changes (one MPD call)."""
        if status.path == self._fav_path:
            return
        self._fav_path = status.path
        self._fav = self.app.mpd.is_favorite(status.path) if status.path else False

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

        elapsed = getattr(status, "elapsed", status.progress * status.duration)
        elapsed_s = int(elapsed)
        if elapsed_s != self._prev_elapsed:
            self._prev_elapsed = elapsed_s
            t = f"{_fmt(elapsed)}  /  {_fmt(status.duration)}"
            self._time_surf = theme.render(t, 11, theme.WHITE)


_TRANSPORT_X = {Button.PREV: 76, Button.PLAY_PAUSE: 160, Button.NEXT: 244}


# ── drawing helpers ───────────────────────────────────────────────────────────

_no_art: pygame.Surface | None = None


def _draw_art(surface: pygame.Surface, art: pygame.Surface | None, a: float) -> None:
    """The hero art (or the "no track" panel) at opacity ``a``."""
    global _no_art
    if art is None:
        if _no_art is None:
            _no_art = pygame.Surface((320, ART_BLEED_H + 10))
            _no_art.fill(theme.BG)
            pygame.draw.rect(_no_art, theme.CARD_BG, (0, 10, 320, ART_BLEED_H))
            lbl = theme.render("no track", 13, theme.DIM)
            _no_art.blit(lbl, lbl.get_rect(center=(160, 10 + ART_BLEED_H // 2)))
        art = _no_art
    motion.blit_alpha(surface, art, (0, -10), a)


def _text(surface: pygame.Surface, surf: pygame.Surface | None, y: int,
          dx: int, a: float) -> None:
    """Centred text line with its drop shadow, shifted ``dx`` at opacity ``a``."""
    if surf is None or a <= 0:
        return
    r = surf.get_rect(centerx=160 + dx, y=y)
    if a >= 1:
        _shadow(surface, surf, r.x, r.y)
        surface.blit(surf, r)
        return
    shadow = surf.copy()
    shadow.fill((0, 0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    motion.blit_alpha(surface, shadow, (r.x + 2, r.y + 2), a)
    motion.blit_alpha(surface, surf, r, a)


def _draw_ripple(surface, at, p, colour) -> None:
    """An expanding, fading disc behind a tapped control."""
    e = motion.ease_out_cubic(p)
    r = int(motion.lerp(12, 30, e))
    disc = pygame.Surface((2 * r + 2, 2 * r + 2), pygame.SRCALPHA)
    pygame.draw.circle(disc, (*colour[:3], int(80 * (1 - e))), (r + 1, r + 1), r)
    surface.blit(disc, (at[0] - r - 1, at[1] - r - 1))


def _scaled_icon(surface, cx, cy, scale, size, draw) -> None:
    """Draw an icon at ``scale`` by rendering it into a small layer first."""
    if abs(scale - 1.0) < 0.01:
        draw(surface, cx, cy)
        return
    layer = pygame.Surface((size, size), pygame.SRCALPHA)
    draw(layer, size // 2, size // 2)
    n = max(2, int(size * scale))
    layer = pygame.transform.smoothscale(layer, (n, n))
    surface.blit(layer, (cx - n // 2, cy - n // 2))


def _draw_play_pause(surface, playing: bool, colour, scale: float) -> None:
    def draw(s, x, y):
        (icons.draw_pause if playing else icons.draw_play)(s, x, y, colour, size="lg")
    _scaled_icon(surface, 160, CTRL_Y, scale, 40, draw)


def _draw_heart(surface, cx, cy, colour, filled: bool, scale: float) -> None:
    _scaled_icon(surface, cx, cy, scale, 28,
                 lambda s, x, y: icons.draw_heart(s, x, y, colour, filled=filled))


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


def _draw_lyrics_icon(surface, cx, cy, col):
    """Speech bubble with text lines — distinct from the queue's plain bars."""
    body = pygame.Rect(cx - 9, cy - 8, 18, 14)
    pygame.draw.rect(surface, col, body, 2, border_radius=4)
    pygame.draw.polygon(surface, col, [
        (cx - 4, cy + 6), (cx + 1, cy + 6), (cx - 3, cy + 10),
    ])
    for i, dy in enumerate((-3, 1)):
        pygame.draw.line(surface, col, (cx - 5, cy + dy),
                         (cx + (4 if i == 0 else 1), cy + dy), 2)


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
