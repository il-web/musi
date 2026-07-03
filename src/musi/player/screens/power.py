"""Power screen — shut down, reboot, or toggle the storage lock (overlay root).

Each action has a confirm step. The storage lock makes the SD card read-only
(hard power cuts can't corrupt it); toggling it rebuilds the initramfs in a
background thread — minutes on a Zero W — and applies on the next reboot.
"""
from __future__ import annotations

import subprocess
import threading

import pygame

from musi.player import audio_detect, hardening, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

SHUTDOWN_RECT = pygame.Rect(30, 88,  260, 72)
REBOOT_RECT   = pygame.Rect(30, 176, 260, 72)
LOCK_RECT     = pygame.Rect(30, 264, 260, 72)
CANCEL_RECT   = pygame.Rect(30, 360, 120, 56)
CONFIRM_RECT  = pygame.Rect(170, 360, 120, 56)

_LOCK_INFO = (
    "SD card becomes read-only after reboot.",
    "Updates & music uploads are disabled",
    "until unlocked.",
)
_UNLOCK_INFO = ("Changes persist again after reboot.",)


class PowerScreen(Screen):
    animates = True   # lock apply runs minutes in the background — never sleep here

    def __init__(self, app) -> None:
        super().__init__(app)
        self._pending: str | None = None   # "shutdown" | "reboot" | "lock"
        self._msg: str = ""
        self._hdr: pygame.Surface | None = None
        self._lock_active: bool = False
        self._lock_conf:   bool = False
        self._lock_busy:   bool = False

    def on_enter(self) -> None:
        self._lock_active = hardening.overlay_active()
        self._lock_conf   = hardening.overlay_configured()

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
            self._lock_card(surface)
        elif self._pending == "lock":
            q = "Unlock storage?" if self._lock_conf else "Lock storage?"
            qs = theme.render(q, 15, theme.WHITE, bold=True)
            surface.blit(qs, qs.get_rect(centerx=160, y=140))
            y = 176
            for line in (_UNLOCK_INFO if self._lock_conf else _LOCK_INFO):
                s = theme.render(line, 11, theme.DIM)
                surface.blit(s, s.get_rect(centerx=160, y=y))
                y += 18
            self._big_button(surface, CANCEL_RECT,  "Cancel", theme.CARD_BG)
            self._big_button(surface, CONFIRM_RECT, "Yes",    theme.ACCENT)
        else:
            label = "Power off the device?" if self._pending == "shutdown" \
                    else "Reboot the device?"
            q = theme.render(label, 15, theme.WHITE, bold=True, max_width=300)
            surface.blit(q, q.get_rect(centerx=160, y=150))
            self._big_button(surface, CANCEL_RECT,  "Cancel", theme.CARD_BG)
            self._big_button(surface, CONFIRM_RECT, "Yes",    (200, 80, 80))

        if self._msg:
            m = theme.render(self._msg, 13, theme.ACCENT, max_width=300)
            surface.blit(m, m.get_rect(centerx=160, y=444))

    def _big_button(self, surface, rect, label, bg):
        pygame.draw.rect(surface, bg, rect, border_radius=12)
        s = theme.render(label, 16, theme.WHITE, bold=True)
        surface.blit(s, s.get_rect(center=rect.center))

    def _lock_card(self, surface) -> None:
        pygame.draw.rect(surface, theme.CARD_BG, LOCK_RECT, border_radius=12)
        t = theme.render("Storage lock", 16, theme.WHITE, bold=True)
        surface.blit(t, (LOCK_RECT.x + 18, LOCK_RECT.y + 12))
        if self._lock_busy:
            state, col = "Applying…", theme.ACCENT
        elif self._lock_active and self._lock_conf:
            state, col = "ON — SD card is read-only", theme.ACCENT
        elif self._lock_conf:
            state, col = "ON after reboot", theme.ACCENT
        elif self._lock_active:
            state, col = "OFF after reboot", theme.DIM
        else:
            state, col = "OFF", theme.DIM
        s = theme.render(state, 11, col)
        surface.blit(s, (LOCK_RECT.x + 18, LOCK_RECT.y + 42))

    # ── input ────────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.BACK
        if self._pending is None:
            if SHUTDOWN_RECT.collidepoint(x, y):
                self._pending = "shutdown"
            elif REBOOT_RECT.collidepoint(x, y):
                self._pending = "reboot"
            elif LOCK_RECT.collidepoint(x, y) and not self._lock_busy:
                self._pending = "lock"
        else:
            if CANCEL_RECT.collidepoint(x, y):
                self._pending = None
            elif CONFIRM_RECT.collidepoint(x, y):
                pending, self._pending = self._pending, None
                if pending == "lock":
                    self._toggle_lock()
                else:
                    self._run(pending)
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.BACK:
            if self._pending is not None:
                self._pending = None
            else:
                self.app.pop()

    # ── actions ───────────────────────────────────────────────────────────────────

    def _run(self, action: str) -> None:
        verb = "poweroff" if action == "shutdown" else "reboot"
        self._msg = "Shutting down…" if action == "shutdown" else "Rebooting…"
        try:
            # -i (--ignore-inhibitors) forces it through immediately instead of
            # waiting on logind inhibitor locks (which made it feel "scheduled").
            subprocess.Popen(["sudo", "systemctl", verb, "-i"], start_new_session=True)
        except Exception as exc:
            self._msg = f"Failed: {exc}"

    def _toggle_lock(self) -> None:
        target = not self._lock_conf
        self._lock_busy = True
        self._msg = "Applying… this can take a few minutes"

        def work() -> None:
            ok, message = hardening.set_overlay(target)
            if ok:
                self._lock_conf = target
                self._msg = "Done — reboot to apply"
            else:
                self._msg = f"Failed: {message}"
            self._lock_busy = False

        threading.Thread(target=work, daemon=True).start()
