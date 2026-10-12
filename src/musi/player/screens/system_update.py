"""System update notice — "run install.sh over SSH", then Restart / Refresh UI.

Shown once by itself when the app starts into that state (after an
over-the-air update that needs install.sh, and again once install.sh has
run), and always as a card in Settings → Updates. It re-checks every couple
of seconds, so while you run install.sh it flips to the Restart / Refresh
button on its own.
"""
from __future__ import annotations

import time

import pygame

from musi.player import audio_detect, statusbar, sysupdate, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

LATER = pygame.Rect(90, 222, 140, 40)
_RECHECK_S = 2.0
_CODE_BG = (16, 16, 24)


def draw_card(surface: pygame.Surface, rect: pygame.Rect,
              su: sysupdate.SystemUpdate, *, compact: bool = False) -> pygame.Rect | None:
    """The notice inside ``rect``; returns the action button's rect (if any)."""
    title, body = sysupdate.TEXT[su.kind]
    pygame.draw.rect(surface, theme.CARD_BG, rect, border_radius=12)
    edge = theme.ACCENT if su.kind == "install" else (90, 200, 130)
    pygame.draw.rect(surface, edge, rect, 1, border_radius=12)
    x, y = rect.x + 14, rect.y + 12
    t = theme.render(title, 15 if compact else 17, theme.WHITE, bold=True,
                     max_width=rect.w - 28)
    surface.blit(t, (x, y))
    y += t.get_height() + 6
    for line in theme.wrap(body, 12, False, rect.w - 28):
        s = theme.render(line, 12, theme.DIM)
        surface.blit(s, (x, y))
        y += s.get_height() + 2
    if su.kind == "install":
        y += 6
        code = pygame.Rect(x, y, rect.w - 28, 30)
        pygame.draw.rect(surface, _CODE_BG, code, border_radius=6)
        c = theme.render(sysupdate.COMMAND, 13, theme.ACCENT, bold=True,
                         max_width=code.w - 16)
        surface.blit(c, c.get_rect(midleft=(code.x + 8, code.centery)))
        y = code.bottom + 8
        hint = theme.render("This screen updates by itself when it's done.",
                            11, theme.DIM, max_width=rect.w - 28)
        surface.blit(hint, (x, y))
        return None
    btn = pygame.Rect(rect.x + 14, rect.bottom - 50, rect.w - 28, 38)
    pygame.draw.rect(surface, theme.ACCENT, btn, border_radius=10)
    b = theme.render(sysupdate.BUTTON[su.kind], 14, theme.WHITE, bold=True)
    surface.blit(b, b.get_rect(center=btn.center))
    return btn


class SystemUpdateScreen(Screen):

    def __init__(self, app, su: sysupdate.SystemUpdate | None = None) -> None:
        super().__init__(app)
        self.su = su or sysupdate.check()
        self._checked = time.monotonic()
        self._msg = ""
        self._btn: pygame.Rect | None = None

    @property
    def animates(self) -> bool:
        return self.su.kind == "install"     # keep polling while install.sh runs

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if time.monotonic() - self._checked >= _RECHECK_S:
            self._checked = time.monotonic()
            self.su = sysupdate.check()
        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        if self.su.kind == "none":
            s = theme.render("All done — the system is up to date", 13,
                             (120, 210, 140), max_width=290)
            surface.blit(s, s.get_rect(center=(160, 200)))
            self._btn = None
        else:
            h = 150 if self.su.kind == "install" else 136
            self._btn = draw_card(surface, pygame.Rect(14, 60, 292, h), self.su)
        lat = theme.render("Later", 13, theme.DIM)
        surface.blit(lat, lat.get_rect(center=LATER.center))
        if self._msg:
            m = theme.render(self._msg, 12, theme.WHITE, max_width=290)
            surface.blit(m, m.get_rect(centerx=160, y=446))

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < statusbar.BAR_H:
            return Button.HOME
        if self._btn and self._btn.collidepoint(x, y):
            self._act()
        elif LATER.collidepoint(x, y):
            self.app.pop()
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.SELECT and self._btn:
            self._act()
        elif button == Button.BACK:
            self.app.pop()

    def _act(self) -> None:
        self._msg = "Restarting…" if self.su.kind == "reboot" else "Refreshing…"
        try:
            sysupdate.act(self.su.kind)
        except Exception as exc:
            self._msg = f"Failed: {exc}"


def maybe_show(app) -> None:
    """Pop the notice up once per state (called when the app reaches Home)."""
    try:
        su = sysupdate.check()
    except Exception:
        return
    if su.kind != "none" and sysupdate.mark_shown(su.kind):
        app.push(SystemUpdateScreen(app, su))
