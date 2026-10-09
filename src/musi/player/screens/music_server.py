"""Music Server settings — sign in to Navidrome (or any Subsonic server) and sync.

Three fields, each typed on the shared keyboard prompt, then one button: it
checks the login with a ping, saves it, and pulls the server's catalog into the
library (subsonic_sync). Audio is never copied — server songs stream, and carry
a cloud tag wherever tracks are listed.

All network work runs on worker threads; the screen only polls their state.
The same setup is also available from a phone through the API
(PUT /api/v1/subsonic).
"""
from __future__ import annotations

import threading
import time

import pygame

from musi.library import config, subsonic
from musi.library.subsonic_sync import job, remove_all
from musi.player import audio_detect, hardening, icons, minibar, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

FIELDS = [("url", "Server"), ("username", "Username"), ("password", "Password")]
ROW_X, ROW_W, ROW_H = 10, 300, 52
ROW_Y   = 92
ROW_GAP = 8
ACTION  = pygame.Rect(30, 290, 260, 56)
SIGNOUT = pygame.Rect(90, 360, 140, 34)

_PHASES = {"connecting": "Connecting", "albums": "Reading albums",
           "songs": "Reading songs", "art": "Fetching covers"}


def row_rect(i: int) -> pygame.Rect:
    return pygame.Rect(ROW_X, ROW_Y + i * (ROW_H + ROW_GAP), ROW_W, ROW_H)


def ago(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return "never"
    s = max(0, int((now or time.time()) - ts))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


class MusicServerScreen(Screen):

    def __init__(self, app) -> None:
        super().__init__(app)
        saved = subsonic.load_settings() or {}
        self.saved = saved
        self.draft = {k: saved.get(k, "") for k, _ in FIELDS}
        self.checking = False           # ping in flight
        self.error = ""
        self._hdr: pygame.Surface | None = None

    @property
    def animates(self) -> bool:
        return self.checking or job.running

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def configured(self) -> bool:
        return bool(self.saved)

    @property
    def dirty(self) -> bool:
        """The fields differ from what is saved — the button connects."""
        return any(self.draft[k] != self.saved.get(k, "") for k, _ in FIELDS)

    def summary(self) -> tuple[str, tuple]:
        if self.checking:
            return "Checking login…", theme.ACCENT
        if job.running:
            phase = _PHASES.get(job.phase, "Syncing")
            if job.total:
                return f"{phase} {job.done}/{job.total}", theme.ACCENT
            return f"{phase}…", theme.ACCENT
        err = self.error or job.error
        if err:
            return f"Failed: {err}", (230, 110, 110)
        if not self.configured:
            return "Stream from Navidrome or any Subsonic server", theme.DIM
        n = self.saved.get("track_count", 0)
        return (f"{n} songs · synced {ago(self.saved.get('last_sync'))}",
                theme.ACCENT)

    def _reload_saved(self) -> None:
        self.saved = subsonic.load_settings() or {}

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._hdr is None:
            self._hdr = theme.render("Music Server", 16, theme.WHITE, bold=True)
        if not job.running and not self.checking and job.stats is not None:
            self._reload_saved()        # pick up track_count / last_sync

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(self._hdr, (14, 26))
        text, col = self.summary()
        surface.blit(theme.render(text, 12, col, max_width=292), (14, 60))

        for i, (key, label) in enumerate(FIELDS):
            r = row_rect(i)
            pygame.draw.rect(surface, theme.CARD_BG, r, border_radius=8)
            surface.blit(theme.render(label, 10, theme.DIM), (r.x + 14, r.y + 8))
            value = self.draft[key]
            if key == "password" and value:
                value = "•" * min(len(value), 16)
            shown = theme.render(value or "Tap to set", 14,
                                 theme.WHITE if value else theme.DIM,
                                 max_width=r.w - 44)
            surface.blit(shown, (r.x + 14, r.y + 24))
            icons.draw_chevron_right(surface, r.right - 14, r.centery, theme.DIM)

        label, enabled = self._action()
        pygame.draw.rect(surface, theme.ACCENT if enabled else theme.CARD_BG,
                         ACTION, border_radius=12)
        icons.draw_cloud(surface, ACTION.x + 28, ACTION.centery,
                         theme.WHITE if enabled else theme.DIM)
        ls = theme.render(label, 16, theme.WHITE if enabled else theme.DIM, bold=True)
        surface.blit(ls, ls.get_rect(center=ACTION.center))

        if self.configured and not self.dirty:
            so = theme.render("Sign out", 12, theme.DIM)
            surface.blit(so, so.get_rect(center=SIGNOUT.center))

        minibar.draw(surface, self.app, status)

    def _action(self) -> tuple[str, bool]:
        busy = self.checking or job.running
        if busy:
            return ("Working…", False)
        if self.dirty or not self.configured:
            ready = all(self.draft[k] for k, _ in FIELDS)
            return ("Connect", ready)
        return ("Sync now", True)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        zone = minibar.hit(x, y)
        if zone == "toggle":
            self.app.toggle_play()
            return None
        if zone == "open":
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return None

        for i, (key, label) in enumerate(FIELDS):
            if row_rect(i).collidepoint(x, y):
                self._edit(key, label)
                return None
        if ACTION.collidepoint(x, y):
            self._act()
            return None
        if self.configured and not self.dirty and SIGNOUT.collidepoint(x, y):
            self._confirm_sign_out()
            return None
        return super().handle_touch(x, y)

    def _edit(self, key: str, label: str) -> None:
        from musi.player.screens.text_entry import TextEntryScreen

        def commit(text: str) -> None:
            self.draft[key] = subsonic.normalize_url(text) if key == "url" else text
            self.error = ""             # the prompt has already popped itself

        initial = "" if key == "password" else self.draft[key]
        self.app.push(TextEntryScreen(self.app, label, initial=initial,
                                      on_commit=commit, max_len=80))

    def _act(self) -> None:
        label, enabled = self._action()
        if not enabled:
            return
        if hardening.overlay_active():
            self.error = "storage lock is on — unlock it in Power"
            return
        if label == "Sync now":
            self._sync()
        else:
            self._connect()

    # ── workers ───────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        """Ping with the draft login; only a good login is saved."""
        self.checking, self.error, job.error = True, "", ""
        draft = dict(self.draft)

        def work() -> None:
            try:
                client = subsonic.Client(draft["url"], draft["username"],
                                         draft["password"])
                client.ping()
                subsonic.save_settings({
                    "url": client.url, "username": draft["username"],
                    "password": draft["password"],
                    "max_bitrate": int(self.saved.get("max_bitrate") or 0),
                })
                self._reload_saved()
                self.draft["url"] = client.url
                self.checking = False
                self._sync()
            except subsonic.SubsonicError as exc:
                self.error = str(exc)
            except OSError as exc:
                self.error = f"could not save login ({exc})"
            finally:
                self.checking = False

        threading.Thread(target=work, daemon=True).start()

    def _sync(self) -> None:
        self.error = ""
        job.start(config.db_path(), self.app.art_dir, on_done=self._reload_saved)

    def _confirm_sign_out(self) -> None:
        from musi.player.screens.context_menu import ContextMenuScreen
        n = self.saved.get("track_count", 0)
        self.app.push(ContextMenuScreen(
            self.app, "Sign out of the server?",
            [(f"Sign out · remove {n} songs", self._sign_out)]))

    def _sign_out(self) -> None:
        if job.running:
            self.error = "wait for the sync to finish"
            return
        subsonic.clear_settings()
        try:
            remove_all(self.app.db)
        except Exception as exc:
            self.error = str(exc)
        self.saved = {}
        self.draft = {k: "" for k, _ in FIELDS}

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.SELECT:
            self._act()
        else:
            super().handle(button, status)
