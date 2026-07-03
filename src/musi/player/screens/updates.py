"""Software Update screen — check GitHub, show the changelog, and pull updates.

Shows current vs latest commit, a "What's new" list of incoming changes, and an
animated staged progress popup while updating.
"""
from __future__ import annotations

import threading

import pygame

from musi.player import audio_detect, hardening, statusbar, theme, updater
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

CHECK_RECT  = pygame.Rect(20, 396, 130, 50)
UPDATE_RECT = pygame.Rect(170, 396, 130, 50)
LOG_Y       = 198          # top of the "What's new" list
LOG_BOTTOM  = 388


class UpdatesScreen(Screen):
    animates = True   # staged progress popup — full FPS, never sleep mid-update

    def __init__(self, app) -> None:
        super().__init__(app)
        self._status: updater.UpdateStatus | None = None
        self._locked: bool = False   # storage lock — git pull wouldn't survive reboot
        self._busy:   bool = False
        self._msg:    str  = ""
        self._hdr:    pygame.Surface | None = None
        self._beta:   pygame.Surface | None = None
        # update progress popup
        self._updating:   bool  = False
        self._prog:       float = 0.0   # target fraction
        self._prog_shown: float = 0.0   # animated (eased) fraction
        self._prog_label: str   = ""

    def on_enter(self) -> None:
        self._locked = hardening.overlay_active()
        self._status = updater.UpdateStatus(current=updater.current_version())
        self._check()

    # ── async actions ───────────────────────────────────────────────────────────

    def _check(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._msg  = "Checking…"

        def work() -> None:
            self._status = updater.check()
            self._msg    = ""
            self._busy   = False

        threading.Thread(target=work, daemon=True).start()

    def _update(self) -> None:
        if self._busy or not (self._status and self._status.available):
            return
        if self._locked:
            self._msg = "Storage locked — unlock in Settings → Power"
            return
        self._busy = True
        self._updating   = True
        self._prog       = 0.0
        self._prog_shown = 0.0
        self._prog_label = "Starting…"

        def cb(frac: float, label: str) -> None:
            self._prog       = frac
            self._prog_label = label

        def work() -> None:
            ok, message = updater.apply(cb)     # on success this restarts the app
            if not ok:
                self._updating = False
                self._busy     = False
                self._msg      = f"Failed: {message}"

        threading.Thread(target=work, daemon=True).start()

    # ── draw ────────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr  = theme.render("musi OS", 30, theme.WHITE, bold=True)
            self._beta = theme.render("beta", 12, theme.ACCENT, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)

        hx, hy = 14, 34
        surface.blit(self._hdr, (hx, hy))
        surface.blit(self._beta,
                     (hx + self._hdr.get_width() + 8,
                      hy + self._hdr.get_height() - self._beta.get_height() - 6))

        st  = self._status
        cur = st.current if st else "?"
        lat = st.latest  if st else "?"
        self._row(surface, 80,  "Current", cur)
        self._row(surface, 116, "Latest",  lat)

        # status line
        if st and st.error:
            line, col = st.error, (230, 120, 120)
        elif st and st.available:
            n = st.behind
            line, col = f"● Update available ({n} commit{'s' if n != 1 else ''})", theme.ACCENT
        elif st and st.is_repo:
            line, col = "Up to date", (120, 210, 140)
        else:
            line, col = "—", theme.DIM
        s = theme.render(line, 13, col, max_width=300)
        surface.blit(s, s.get_rect(centerx=160, y=164))

        # "What's new" changelog
        if st and st.available and st.changelog:
            self._draw_changelog(surface, st.changelog)

        # buttons
        self._button(surface, CHECK_RECT, "Check", enabled=not self._busy)
        can_update = bool(st and st.available) and not self._busy and not self._locked
        self._button(surface, UPDATE_RECT, "Update now", enabled=can_update, accent=can_update)

        if self._msg and not self._updating:
            m = theme.render(self._msg, 12, theme.WHITE, max_width=300)
            surface.blit(m, m.get_rect(centerx=160, y=458))
        elif self._locked and not self._updating:
            m = theme.render("Storage locked — unlock in Settings → Power to update",
                             11, theme.DIM, max_width=300)
            surface.blit(m, m.get_rect(centerx=160, y=458))

        # progress popup (modal) — drawn last, over everything
        if self._updating:
            self._draw_progress(surface)

    def _draw_changelog(self, surface, log: list[str]) -> None:
        title = theme.render("What's new", 11, theme.DIM, bold=True)
        surface.blit(title, (20, LOG_Y))
        y = LOG_Y + 20
        line_h = 19
        shown = 0
        for msg in log:
            if y + line_h > LOG_BOTTOM:
                remaining = len(log) - shown
                more = theme.render(f"+{remaining} more…", 10, theme.DIM)
                surface.blit(more, (28, y))
                break
            dot = theme.render("•", 12, theme.ACCENT)
            surface.blit(dot, (20, y))
            ln = theme.render(msg, 11, theme.WHITE, max_width=280)
            surface.blit(ln, (32, y))
            y += line_h
            shown += 1

    def _draw_progress(self, surface) -> None:
        # ease the visible bar toward the target each frame
        self._prog_shown += (self._prog - self._prog_shown) * 0.18

        dim = pygame.Surface((320, 480), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 185))
        surface.blit(dim, (0, 0))

        box = pygame.Rect(0, 0, 280, 132)
        box.center = (160, 240)
        pygame.draw.rect(surface, theme.CARD_BG, box, border_radius=14)

        title = theme.render("Updating", 16, theme.WHITE, bold=True)
        surface.blit(title, title.get_rect(centerx=160, y=box.y + 18))
        lbl = theme.render(self._prog_label, 12, theme.ACCENT, max_width=250)
        surface.blit(lbl, lbl.get_rect(centerx=160, y=box.y + 48))

        bx, by, bw, bh = box.x + 24, box.y + 80, box.width - 48, 8
        pygame.draw.rect(surface, (40, 40, 56), (bx, by, bw, bh), border_radius=4)
        fill = max(0, min(bw, int(bw * self._prog_shown)))
        if fill > 0:
            pygame.draw.rect(surface, theme.ACCENT, (bx, by, fill, bh), border_radius=4)
        pct = theme.render(f"{int(self._prog_shown * 100)}%", 10, theme.DIM)
        surface.blit(pct, pct.get_rect(centerx=160, y=by + 14))

    def _row(self, surface, y, label, value):
        l = theme.render(label, 12, theme.DIM)
        surface.blit(l, (24, y))
        v = theme.render(value, 14, theme.WHITE, bold=True)
        surface.blit(v, (140, y - 2))

    def _button(self, surface, rect, label, enabled, accent=False):
        if accent and enabled:
            bg, fg = theme.ACCENT, theme.WHITE
        elif enabled:
            bg, fg = theme.CARD_BG, theme.WHITE
        else:
            bg, fg = (24, 24, 32), (90, 90, 105)
        pygame.draw.rect(surface, bg, rect, border_radius=10)
        s = theme.render(label, 13, fg, bold=True)
        surface.blit(s, s.get_rect(center=rect.center))

    # ── input ────────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if self._updating:
            return None        # modal — block input during update
        if y < 26:
            return Button.BACK
        if CHECK_RECT.collidepoint(x, y):
            self._check()
        elif UPDATE_RECT.collidepoint(x, y):
            self._update()
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if self._updating:
            return
        if button == Button.BACK:
            self.app.pop()
        elif button == Button.SELECT:
            self._update()
