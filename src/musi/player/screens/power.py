"""Power screen — shut down or reboot the device (with a confirm step)."""
from __future__ import annotations

import subprocess

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

SHUTDOWN_RECT = pygame.Rect(30, 96,  260, 76)
REBOOT_RECT   = pygame.Rect(30, 196, 260, 76)
CANCEL_RECT   = pygame.Rect(30, 340, 120, 56)
CONFIRM_RECT  = pygame.Rect(170, 340, 120, 56)


class PowerScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        self._pending: str | None = None   # "shutdown" | "reboot" while confirming
        self._msg: str = ""
        self._hdr: pygame.Surface | None = None

    # ── draw ────────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr = theme.render("Power", 16, theme.WHITE, bold=True)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_back=len(self.app.stack) > 1)
        surface.blit(self._hdr, (14, 26))

        if self._pending is None:
            self._big_button(surface, SHUTDOWN_RECT, "Shut down", (200, 80, 80))
            self._big_button(surface, REBOOT_RECT,   "Reboot",    theme.CARD_BG)
        else:
            label = "Power off the device?" if self._pending == "shutdown" \
                    else "Reboot the device?"
            q = theme.render(label, 15, theme.WHITE, bold=True, max_width=300)
            surface.blit(q, q.get_rect(centerx=160, y=150))
            self._big_button(surface, CANCEL_RECT,  "Cancel", theme.CARD_BG)
            self._big_button(surface, CONFIRM_RECT, "Yes",    (200, 80, 80))

        if self._msg:
            m = theme.render(self._msg, 13, theme.ACCENT, max_width=300)
            surface.blit(m, m.get_rect(centerx=160, y=430))

    def _big_button(self, surface, rect, label, bg):
        pygame.draw.rect(surface, bg, rect, border_radius=12)
        s = theme.render(label, 16, theme.WHITE, bold=True)
        surface.blit(s, s.get_rect(center=rect.center))

    # ── input ────────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.BACK
        if self._pending is None:
            if SHUTDOWN_RECT.collidepoint(x, y):
                self._pending = "shutdown"
            elif REBOOT_RECT.collidepoint(x, y):
                self._pending = "reboot"
        else:
            if CANCEL_RECT.collidepoint(x, y):
                self._pending = None
            elif CONFIRM_RECT.collidepoint(x, y):
                self._run(self._pending)
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            if self._pending is not None:
                self._pending = None
            else:
                self.app.pop()

    # ── action ────────────────────────────────────────────────────────────────────

    def _run(self, action: str) -> None:
        verb = "poweroff" if action == "shutdown" else "reboot"
        self._msg = "Shutting down…" if action == "shutdown" else "Rebooting…"
        self._pending = None
        try:
            # -i (--ignore-inhibitors) forces it through immediately instead of
            # waiting on logind inhibitor locks (which made it feel "scheduled").
            subprocess.Popen(["sudo", "systemctl", verb, "-i"], start_new_session=True)
        except Exception as exc:
            self._msg = f"Failed: {exc}"
