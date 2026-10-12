"""Radio app — saved stations, stations near you, and search.

Home: your saved stations, then TuneIn's "local radio" for where the device
is. Search opens a results list (TuneIn, falling back to Radio Browser —
library/radio.py). Tap a station to play it; the heart on the right saves it.

On top sits SUB/WAVE — your own AI-DJ station (library/subwave.py): connect
it by address, play it, and send the DJ song requests.

All network work (directory calls, tuning, logo downloads) runs on worker
threads; draw() only reads the state they leave behind.
"""
from __future__ import annotations

import threading
import time

import pygame

from musi.library import radio, remote, subwave
from musi.player import art_cache, audio_detect, icons, minibar, radio_play, statusbar, theme
from musi.player.input import Button
from musi.player.list_screen import ListScreen
from musi.player.mpd_client import PlayerStatus

SEARCH_RECT = pygame.Rect(10, 56, 300, 36)
MSG_Y   = 98
LIST_Y  = 116
ITEM_H  = 56
HEART_X = 262          # taps right of this toggle "saved"
LOGO    = 40


class _StationList(ListScreen):
    """Rows of ("header", text) / ("note", text) / ("station", dict) /
    ("action", (key, label)) — a button row, see on_action."""

    title = "Radio"

    def __init__(self, app) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=minibar.BAR_Y)
        self.rows: list[tuple[str, object]] = []
        self.msg = ""
        self._open_now_playing = False
        self._logos: dict[tuple, pygame.Surface | None] = {}
        self._logo_check = 0.0

    def set_rows(self, rows: list[tuple[str, object]]) -> None:
        self.rows = rows
        self._klist.set_count(len(rows))

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._open_now_playing:              # set by a worker; push here
            self._open_now_playing = False
            from musi.player.screens.now_playing import NowPlayingScreen
            self.app.push(NowPlayingScreen(self.app))
            return
        if self._klist.count != len(self.rows):
            self._klist.set_count(len(self.rows))
        if time.monotonic() >= self._logo_check:   # logos still downloading?
            self._logo_check = time.monotonic() + 1.0
            for k in [k for k, v in self._logos.items() if v is None]:
                del self._logos[k]

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(),
                       show_home=len(self.app.stack) > 1)
        surface.blit(theme.render(self.title, 16, theme.WHITE, bold=True,
                                  max_width=292), (14, 28))

        pygame.draw.rect(surface, theme.CARD_BG, SEARCH_RECT, border_radius=18)
        _magnifier(surface, SEARCH_RECT.x + 20, SEARCH_RECT.centery)
        hint = theme.render("Search stations", 13, theme.DIM)
        surface.blit(hint, (SEARCH_RECT.x + 36, SEARCH_RECT.centery - hint.get_height() // 2))

        if self.msg:
            m = theme.render(self.msg, 11, theme.ACCENT, max_width=292)
            surface.blit(m, (14, MSG_Y))

        self._on_air = radio_play.current_station(self.app)
        self.draw_list_viewport(surface, len(self.rows))
        minibar.draw(surface, self.app, status)

    def _draw_row(self, surface: pygame.Surface, y: int, i: int) -> None:
        kind, value = self.rows[i]
        if kind == "header":
            h = theme.render(str(value), 12, theme.DIM, bold=True)
            surface.blit(h, (14, y + ITEM_H - h.get_height() - 8))
            return
        if kind == "note":
            n = theme.render(str(value), 11, theme.DIM, max_width=292)
            surface.blit(n, (14, y + (ITEM_H - n.get_height()) // 2))
            return
        if kind == "action":
            _key, label = value
            sel = i == self._sel and self._tap.pending
            rect = pygame.Rect(8, y + 2, 304, ITEM_H - 4)
            pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG, rect,
                             border_radius=8)
            pygame.draw.rect(surface, theme.ACCENT, rect, 1, border_radius=8)
            col = theme.WHITE if sel else theme.ACCENT
            icons.draw_plus(surface, 34, y + ITEM_H // 2, col)
            lbl = theme.render(str(label), 13, col, bold=True, max_width=230)
            surface.blit(lbl, (64, y + (ITEM_H - lbl.get_height()) // 2))
            return

        st: dict = value                                    # a station
        sel = i == self._sel and self._tap.pending
        rect = pygame.Rect(8, y + 2, 304, ITEM_H - 4)
        pygame.draw.rect(surface, theme.ACCENT if sel else theme.CARD_BG, rect,
                         border_radius=8)

        logo = self._logo(st)
        lx, ly = 14, y + (ITEM_H - LOGO) // 2
        if logo is not None:
            surface.blit(logo, (lx, ly))
        else:
            pygame.draw.rect(surface, (40, 40, 55), (lx, ly, LOGO, LOGO), border_radius=6)
            icons.draw_radio(surface, lx + LOGO // 2, ly + LOGO // 2, (110, 110, 130))

        on_air = bool(self._on_air) and (self._on_air.get("provider"), self._on_air.get("id")) \
            == (st.get("provider"), st.get("id"))
        name_col = theme.WHITE if sel or not on_air else theme.ACCENT
        name = theme.render(st.get("name", "?"), 13, name_col, bold=on_air, max_width=196)
        surface.blit(name, (64, y + 10))
        sub = "● On air" if on_air else st.get("subtext", "")
        s = theme.render(sub, 10, theme.WHITE if sel else theme.DIM, max_width=196)
        surface.blit(s, (64, y + 30))

        saved = radio.is_saved(st)
        icons.draw_heart(surface, 288, y + ITEM_H // 2,
                         theme.ACCENT if saved and not sel else theme.WHITE if sel else theme.DIM,
                         filled=saved)

    def _logo(self, st: dict) -> pygame.Surface | None:
        """40 px logo, cached per screen; None while it downloads."""
        key = (st.get("provider"), st.get("id"))
        if key not in self._logos:
            path = radio.ensure_logo(st)
            self._logos[key] = art_cache.load_surface(str(path), (LOGO, LOGO)) if path else None
        return self._logos[key]

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
        if SEARCH_RECT.collidepoint(x, y):
            self._search()
            return None
        if LIST_Y <= y < minibar.BAR_Y and not self._tap.pending:
            i = self._klist.index_at(y - LIST_Y)
            if 0 <= i < len(self.rows) and self.rows[i][0] == "action":
                self._sel = i
                key = self.rows[i][1][0]
                self._tap.set(lambda key=key: self.on_action(key))
                return None
            if 0 <= i < len(self.rows) and self.rows[i][0] == "station":
                st = self.rows[i][1]
                if x >= HEART_X:
                    radio.toggle_saved(st)
                    self.on_saved_changed()
                else:
                    self._sel = i
                    self._tap.set(lambda st=st: self.play(st))
                return None
        return super().handle_touch(x, y)

    def on_saved_changed(self) -> None:
        """Hook: the home list rebuilds its "Saved" section."""

    def on_action(self, key: str) -> None:
        """Hook: a button row was tapped."""

    def _search(self) -> None:
        from musi.player.screens.text_entry import TextEntryScreen

        def go(query: str) -> None:
            self.app.push(RadioSearchScreen(self.app, query))

        self.app.push(TextEntryScreen(self.app, "Search stations", on_commit=go))

    def play(self, st: dict) -> None:
        self.msg = f"Tuning in to {st.get('name', '?')}…"

        def done(error: str | None) -> None:
            if error:
                self.msg = f"Couldn't tune in: {error}"
            else:
                self.msg = ""
                self._open_now_playing = True

        radio_play.play_station(self.app, st, on_done=done)

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.DOWN:
            self._sel = min(len(self.rows) - 1, self._sel + 1)
            self._clamp_scroll()
        elif button == Button.SELECT and 0 <= self._sel < len(self.rows):
            kind, value = self.rows[self._sel]
            if kind == "station":
                self.play(value)
            elif kind == "action":
                self.on_action(value[0])
        else:
            super().handle(button, status)


class RadioScreen(_StationList):
    """The app's home: saved stations, then stations near you."""

    title = "Radio"

    def __init__(self, app) -> None:
        super().__init__(app)
        self.local: list[dict] | None = None    # None = still loading
        self.local_error = ""

    def on_enter(self) -> None:
        self._rebuild()
        if self.local is None and not self.local_error:
            def work() -> None:
                try:
                    self.local = radio.tunein_local()
                except radio.RadioError as exc:
                    self.local_error = str(exc)
                    self.local = []
                self._rebuild()

            threading.Thread(target=work, daemon=True).start()

    def on_saved_changed(self) -> None:
        self._rebuild()

    # ── SUB/WAVE ──────────────────────────────────────────────────────────────

    def on_action(self, key: str) -> None:
        from musi.player.screens.text_entry import TextEntryScreen
        if key == "sw-connect":
            cur = subwave.load()
            self.app.push(TextEntryScreen(
                self.app, "SUB/WAVE address", initial=cur["id"] if cur else "",
                on_commit=self.connect_subwave, max_len=80))
        elif key == "sw-request":
            self.app.push(TextEntryScreen(
                self.app, "Ask the DJ for…", on_commit=self.request_song, max_len=80))

    def connect_subwave(self, address: str) -> None:
        self.msg = "Looking for your station…"

        def work() -> None:
            try:
                st = subwave.connect(address)
                subwave.save(st)
                self.msg = f"Connected to {st['name']}"
            except (subwave.SubwaveError, OSError) as exc:
                self.msg = f"Couldn't connect: {exc}"
            self._rebuild()

        threading.Thread(target=work, daemon=True).start()

    def request_song(self, text: str) -> None:
        st = subwave.load()
        if not st:
            return
        self.msg = "Asking the DJ…"

        def work() -> None:
            try:
                self.msg = subwave.request_and_wait(st, text)
            except subwave.SubwaveError as exc:
                self.msg = f"Request failed: {exc}"

        threading.Thread(target=work, daemon=True).start()

    def handle_long_press(self, x: int, y: int) -> bool:
        if not (LIST_Y <= y < minibar.BAR_Y):
            return False
        i = self._klist.index_at(y - LIST_Y)
        row = self.rows[i] if 0 <= i < len(self.rows) else None
        if row is None or row[0] != "station" or not subwave.is_subwave(row[1]):
            return False
        from musi.player.screens.context_menu import ContextMenuScreen

        def disconnect() -> None:
            subwave.forget()
            self.msg = ""
            self._rebuild()

        self.app.push(ContextMenuScreen(self.app, "SUB/WAVE", [
            ("Change address…", lambda: self.on_action("sw-connect")),
            ("Disconnect",      disconnect),
        ]))
        return True

    def _rebuild(self) -> None:
        sw = subwave.load()
        rows: list[tuple[str, object]] = [("header", "SUB/WAVE")]
        if sw:
            rows += [("station", sw), ("action", ("sw-request", "Request a song"))]
        else:
            rows.append(("action", ("sw-connect", "Connect your SUB/WAVE station")))
        # a saved SUB/WAVE stays in next/prev rotation but is listed once, above
        saved = [s for s in radio.saved() if not subwave.is_subwave(s)]
        rows.append(("header", "Saved"))
        if saved:
            rows += [("station", s) for s in saved]
        else:
            rows.append(("note", "Tap the heart on a station to save it here."))
        rows.append(("header", "Near you"))
        if self.local is None:
            rows.append(("note", "Loading…"))
        elif self.local_error:
            rows.append(("note", f"Couldn't load: {self.local_error}"))
        else:
            mine = {(s["provider"], s["id"]) for s in saved}
            rows += [("station", s) for s in self.local
                     if (s["provider"], s["id"]) not in mine]
        self.set_rows(rows)


class RadioSearchScreen(_StationList):

    def __init__(self, app, query: str) -> None:
        super().__init__(app)
        self.query = query
        self.title = f"“{query}”"
        self.set_rows([("note", "Searching…")])

    def on_enter(self) -> None:
        if self.rows != [("note", "Searching…")]:
            return

        def work() -> None:
            try:
                found, source = radio.search(self.query)
            except radio.RadioError as exc:
                self.set_rows([("note", f"Search failed: {exc}")])
                return
            if not found:
                self.set_rows([("note", "No stations found.")])
                return
            label = "TuneIn" if source == "tunein" else "Radio Browser"
            self.set_rows([("header", f"{len(found)} stations · via {label}")]
                          + [("station", s) for s in found])

        threading.Thread(target=work, daemon=True).start()


def _magnifier(surface: pygame.Surface, cx: int, cy: int) -> None:
    pygame.draw.circle(surface, theme.DIM, (cx - 2, cy - 2), 6, 2)
    pygame.draw.line(surface, theme.DIM, (cx + 2, cy + 2), (cx + 7, cy + 7), 2)


def subtitle(app) -> str:
    """Launcher line: what's on air, else how many stations are saved."""
    st = radio_play.current_station(app) if remote.is_radio(app.status.path) else None
    if st and app.status.state == "play":
        return f"On air: {st.get('name', '?')}"
    n = len(radio.saved())
    return "Search stations" if n == 0 else f"{n} saved station" + ("" if n == 1 else "s")
