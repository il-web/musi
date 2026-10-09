"""'musi keeps crashing' — offered at startup after a crash loop on a fresh update.

The user chooses: roll back to the version the update replaced, or keep this
one (and not be asked again about it). See player/crashguard.py for when this
appears. Kept deliberately plain — no animation, no list, nothing that could
share a bug with whatever is crashing.
"""
from __future__ import annotations

import threading

import pygame

from musi.player import crashguard, hardening, theme, updater
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

ROLLBACK_RECT = pygame.Rect(24, 330, 272, 54)
KEEP_RECT     = pygame.Rect(24, 396, 272, 48)


class RollbackScreen(Screen):

    def __init__(self, app, offer: dict, then: Screen) -> None:
        super().__init__(app)
        self.offer = offer
        self._then = then
        self.working = False
        self.label = ""
        self.error = ""

    @property
    def animates(self) -> bool:
        return self.working

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        o = self.offer
        surface.fill(theme.BG)
        y = 52
        surface.blit(theme.render("musi keeps crashing", 20, theme.WHITE, bold=True), (24, y))
        y += 40
        body = (f"It crashed {o['count']} times in the last few minutes, "
                f"since updating to {o['version'][:7]}.")
        for row in theme.wrap(body, 13, False, 272):
            surface.blit(theme.render(row, 13, theme.WHITE), (24, y))
            y += 20

        if o.get("reason"):
            y += 14
            surface.blit(theme.render("Last crash", 11, theme.DIM, bold=True), (24, y))
            y += 18
            for row in theme.wrap(o["reason"], 11, False, 272)[:4]:
                surface.blit(theme.render(row, 11, theme.DIM, max_width=272), (24, y))
                y += 16

        if self.working or self.error:
            text = self.error or self.label
            col = (230, 120, 120) if self.error else theme.ACCENT
            for i, row in enumerate(theme.wrap(text, 12, False, 272)[:2]):
                s = theme.render(row, 12, col, max_width=272)
                surface.blit(s, s.get_rect(centerx=160, y=282 + i * 18))

        enabled = not self.working
        pygame.draw.rect(surface, theme.ACCENT if enabled else theme.CARD_BG,
                         ROLLBACK_RECT, border_radius=12)
        s = theme.render(f"Roll back to {o['target'][:7]}", 15,
                         theme.WHITE if enabled else theme.DIM, bold=True)
        surface.blit(s, s.get_rect(center=ROLLBACK_RECT.center))

        pygame.draw.rect(surface, theme.CARD_BG, KEEP_RECT, border_radius=12)
        s = theme.render("Keep this version", 14, theme.WHITE if enabled else theme.DIM)
        surface.blit(s, s.get_rect(center=KEEP_RECT.center))

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if self.working:
            return None
        if ROLLBACK_RECT.collidepoint(x, y):
            self.roll_back()
        elif KEEP_RECT.collidepoint(x, y):
            self.keep()
        return None

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if self.working:
            return
        if button == Button.SELECT:
            self.roll_back()
        elif button in (Button.BACK, Button.HOME):
            self.keep()

    def go_back(self) -> None:
        if not self.working:
            self.keep()

    # ── actions ───────────────────────────────────────────────────────────────

    def keep(self) -> None:
        """Carry on with this version; don't ask about it again."""
        crashguard.decline(self.offer["version"])
        self.app._stack.clear()
        self.app.push(self._then)

    def roll_back(self) -> None:
        if hardening.overlay_active():
            self.error = "Storage lock is on — a rollback wouldn't survive a reboot."
            return
        self.working, self.error, self.label = True, "", "Starting…"

        def progress(_frac: float, label: str) -> None:
            self.label = label

        def work() -> None:
            ok, msg = updater.rollback(self.offer["target"], progress)
            if not ok:                  # success restarts the app under us
                self.working = False
                self.error = f"Rollback failed: {msg}"

        threading.Thread(target=work, daemon=True).start()
