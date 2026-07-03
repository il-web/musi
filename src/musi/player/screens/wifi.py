"""WiFi network selection and connection screen."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

import pygame

from musi.player import audio_detect, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen

# ── character wheel for Pi button input ───────────────────────────────────────
_CHARS = list(
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " !@#$%&*()-_=+.,?/"
)

# ── layout ────────────────────────────────────────────────────────────────────
LIST_Y  = 64
ITEM_H  = 50
NAV_Y   = 456
MAX_VIS = (NAV_Y - LIST_Y) // ITEM_H   # 7

# ── states ────────────────────────────────────────────────────────────────────
_S_SCANNING   = "scanning"
_S_LIST       = "list"
_S_PASSWORD   = "password"
_S_CONNECTING = "connecting"
_S_DONE       = "done"
_S_ERROR      = "error"
_S_UNSUPPORTED= "unsupported"


@dataclass
class _Network:
    ssid:      str
    signal:    int    # 0–100
    secured:   bool
    connected: bool = False


class WifiScreen(Screen):
    animates = True   # scan/connect spinners — full FPS, no sleep

    def __init__(self, app) -> None:
        super().__init__(app)
        self._state:    str            = _S_SCANNING
        self._networks: list[_Network] = []
        self._sel:      int            = 0
        self._scroll:   int            = 0

        # password entry
        self._target:   _Network | None = None
        self._password: str             = ""
        self._char_idx: int             = 0       # char wheel position

        # result message
        self._message:  str = ""
        self._ip:       str = ""

        self._spin_t:   float = 0.0
        self._nav_surf: pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._spin_t = time.monotonic()
        if sys.platform != "linux":
            self._state = _S_UNSUPPORTED
            return
        self._state = _S_SCANNING
        threading.Thread(target=self._scan, daemon=True).start()

    # ── raw keyboard input (desktop / Pi with USB keyboard) ───────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        if self._state != _S_PASSWORD:
            return False
        if event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_RETURN:
            self._do_connect()
            return True
        if event.key == pygame.K_BACKSPACE:
            if self._password:
                self._password = self._password[:-1]
                return True
            return False
        if event.unicode and event.unicode.isprintable():
            self._password += event.unicode
            return True
        return False

    # ── touch input ──────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if self._state == _S_LIST and LIST_Y <= y < NAV_Y - 24:
            vi = (y - LIST_Y) // ITEM_H
            di = vi + self._scroll
            if 0 <= di < len(self._networks):
                self._sel = di
                self._clamp_scroll()
                self._handle_list(Button.SELECT)
                return None
        return super().handle_touch(x, y)

    # ── button input ─────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if self._state == _S_LIST:
            self._handle_list(button)
        elif self._state == _S_PASSWORD:
            self._handle_password(button)
        elif self._state in (_S_DONE, _S_ERROR, _S_UNSUPPORTED):
            if button == Button.BACK:
                self.app.pop()
        elif self._state == _S_SCANNING:
            if button == Button.BACK:
                self.app.pop()

    def _handle_list(self, button: Button) -> None:
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
            self._clamp_scroll()
        elif button == Button.DOWN:
            self._sel = min(len(self._networks) - 1, self._sel + 1)
            self._clamp_scroll()
        elif button == Button.SELECT:
            if self._networks:
                net = self._networks[self._sel]
                if net.secured:
                    self._target   = net
                    self._password = ""
                    self._char_idx = 0
                    self._state    = _S_PASSWORD
                else:
                    self._target = net
                    self._do_connect()
        elif button == Button.BACK:
            self.app.pop()
        elif button == Button.PLAY_PAUSE:
            # Refresh
            self._state = _S_SCANNING
            threading.Thread(target=self._scan, daemon=True).start()

    def _handle_password(self, button: Button) -> None:
        if button == Button.UP:
            self._char_idx = (self._char_idx - 1) % len(_CHARS)
        elif button == Button.DOWN:
            self._char_idx = (self._char_idx + 1) % len(_CHARS)
        elif button == Button.SELECT:
            # Add current char from wheel
            self._password += _CHARS[self._char_idx]
        elif button == Button.BACK:
            if self._password:
                self._password = self._password[:-1]
            else:
                self._state = _S_LIST
        elif button == Button.PLAY_PAUSE:
            self._do_connect()
        elif button == Button.NEXT:
            # Quick-add space
            self._password += " "
        elif button == Button.PREV:
            # Delete last char
            if self._password:
                self._password = self._password[:-1]

    # ── scan ─────────────────────────────────────────────────────────────────

    def _scan(self) -> None:
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                 "device", "wifi", "list", "--rescan", "yes"],
                capture_output=True, text=True, timeout=20,
            )
            nets: list[_Network] = []
            seen: set[str] = set()
            for line in r.stdout.strip().splitlines():
                parts = line.split(":", 3)
                if len(parts) < 4:
                    continue
                in_use, ssid, sig, sec = parts
                ssid = ssid.strip()
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                nets.append(_Network(
                    ssid      = ssid,
                    signal    = int(sig) if sig.strip().isdigit() else 0,
                    secured   = bool(sec.strip()),
                    connected = (in_use.strip() == "*"),
                ))
            nets.sort(key=lambda n: (-n.connected, -n.signal))
            self._networks = nets
            self._sel      = 0
            self._scroll   = 0
            self._state    = _S_LIST
        except Exception as exc:
            self._message = str(exc)
            self._state   = _S_ERROR

    # ── connect ──────────────────────────────────────────────────────────────

    def _do_connect(self) -> None:
        if not self._target:
            return
        self._state = _S_CONNECTING
        net = self._target
        pwd = self._password
        threading.Thread(target=self._connect_thread, args=(net, pwd), daemon=True).start()

    def _connect_thread(self, net: _Network, password: str) -> None:
        cmd = ["nmcli", "device", "wifi", "connect", net.ssid]
        if net.secured and password:
            cmd += ["password", password]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                # Get IP
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    self._ip = s.getsockname()[0]
                    s.close()
                except Exception:
                    self._ip = ""
                self._message = f"Connected to {net.ssid}"
                self._state   = _S_DONE
            else:
                self._message = (r.stderr.strip() or r.stdout.strip()
                                 or "Connection failed")[:80]
                self._state   = _S_ERROR
        except subprocess.TimeoutExpired:
            self._message = "Connection timed out"
            self._state   = _S_ERROR
        except Exception as exc:
            self._message = str(exc)
            self._state   = _S_ERROR

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._nav_surf is None:
            self._nav_surf = theme.render("Esc = back", 10, theme.DIM)

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_back=len(self.app.stack) > 1)

        hdr = theme.render("WiFi", 14, theme.WHITE, bold=True)
        surface.blit(hdr, (14, 24))

        {
            _S_SCANNING:    self._draw_scanning,
            _S_LIST:        self._draw_list,
            _S_PASSWORD:    self._draw_password,
            _S_CONNECTING:  self._draw_connecting,
            _S_DONE:        self._draw_done,
            _S_ERROR:       self._draw_error,
            _S_UNSUPPORTED: self._draw_unsupported,
        }[self._state](surface)

        surface.blit(self._nav_surf,
                     self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    # ── sub-draw ──────────────────────────────────────────────────────────────

    def _draw_scanning(self, surface: pygame.Surface) -> None:
        _spinner(surface, 160, 230, time.monotonic() - self._spin_t)
        msg = theme.render("Scanning for networks…", 12, theme.DIM)
        surface.blit(msg, msg.get_rect(centerx=160, y=256))

    def _draw_list(self, surface: pygame.Surface) -> None:
        if not self._networks:
            msg = theme.render("No networks found", 13, theme.DIM)
            surface.blit(msg, msg.get_rect(centerx=160, y=230))
            hint = theme.render("Space = refresh", 10, theme.DIM)
            surface.blit(hint, hint.get_rect(centerx=160, y=256))
            return

        # refresh hint top-right
        ref_s = theme.render("Space = refresh", 9, theme.DIM)
        surface.blit(ref_s, ref_s.get_rect(right=312, y=28))

        for vi in range(MAX_VIS):
            di = vi + self._scroll
            if di >= len(self._networks):
                break
            net = self._networks[di]
            y   = LIST_Y + vi * ITEM_H
            sel = (di == self._sel)

            rect = pygame.Rect(8, y, 304, ITEM_H - 3)
            pygame.draw.rect(surface,
                             theme.ACCENT if sel else theme.CARD_BG,
                             rect, border_radius=7)

            col = theme.WHITE

            # signal bars
            _signal_bars(surface, 22, y + (ITEM_H - 3) // 2, net.signal,
                         theme.WHITE if sel else theme.DIM)

            # SSID
            max_w = 210 if net.secured else 230
            ssid_s = theme.render(net.ssid, 12, col, bold=(sel or net.connected),
                                  max_width=max_w)
            surface.blit(ssid_s, (42, y + (ITEM_H - 3 - ssid_s.get_height()) // 2))

            # lock icon for secured networks
            if net.secured:
                _lock(surface, 270, y + (ITEM_H - 3) // 2,
                      theme.WHITE if sel else theme.DIM)

            # connected checkmark
            if net.connected:
                ck_s = theme.render("✓", 11, (80, 200, 120))
                surface.blit(ck_s, ck_s.get_rect(right=306,
                             centery=y + (ITEM_H - 3) // 2))

        if len(self._networks) > MAX_VIS:
            _scrollbar(surface, 314, LIST_Y, NAV_Y - LIST_Y,
                       len(self._networks), self._scroll, MAX_VIS)

    def _draw_password(self, surface: pygame.Surface) -> None:
        # target SSID
        net_s = theme.render(
            f"Connect to: {self._target.ssid}" if self._target else "Password",
            13, theme.WHITE, bold=True, max_width=296,
        )
        surface.blit(net_s, net_s.get_rect(centerx=160, y=68))

        # password box
        box_rect = pygame.Rect(8, 98, 304, 42)
        pygame.draw.rect(surface, (28, 28, 42), box_rect, border_radius=6)
        pygame.draw.rect(surface, theme.ACCENT, box_rect, 1, border_radius=6)

        t           = time.monotonic()
        cursor      = "|" if int(t * 2) % 2 == 0 else " "
        display_pwd = "•" * len(self._password) + cursor
        pwd_s       = theme.render(display_pwd, 13, theme.WHITE, max_width=290)
        surface.blit(pwd_s, (18, 107))

        # ── character wheel ───────────────────────────────────────────────────
        pygame.draw.line(surface, (35, 35, 50), (8, 152), (312, 152), 1)
        whl_s = theme.render("▲ ▼ scroll  •  Enter / ▶‖ = connect  •  Esc = back",
                             9, theme.DIM, max_width=296)
        surface.blit(whl_s, whl_s.get_rect(centerx=160, y=160))

        # show prev / current / next chars
        prev_c = _CHARS[(self._char_idx - 1) % len(_CHARS)]
        curr_c = _CHARS[self._char_idx]
        next_c = _CHARS[(self._char_idx + 1) % len(_CHARS)]

        prev_s = theme.render(repr(prev_c)[1:-1], 14, theme.DIM)
        curr_s = theme.render(repr(curr_c)[1:-1], 26, theme.WHITE, bold=True)
        next_s = theme.render(repr(next_c)[1:-1], 14, theme.DIM)

        # highlight box behind current char — centered vertically at 220
        pygame.draw.rect(surface, theme.CARD_BG,
                         pygame.Rect(132, 196, 56, 48), border_radius=6)
        pygame.draw.rect(surface, theme.ACCENT,
                         pygame.Rect(132, 196, 56, 48), 1, border_radius=6)

        surface.blit(curr_s, curr_s.get_rect(centerx=160, centery=220))
        surface.blit(prev_s, prev_s.get_rect(centerx=84,  centery=220))
        surface.blit(next_s, next_s.get_rect(centerx=236, centery=220))

        # arrows
        arr_col = theme.DIM
        pygame.draw.polygon(surface, arr_col, [(160, 186), (154, 196), (166, 196)])
        pygame.draw.polygon(surface, arr_col, [(160, 254), (154, 244), (166, 244)])

        # select hint
        sel_s = theme.render("Select = add char", 10, theme.DIM)
        surface.blit(sel_s, sel_s.get_rect(centerx=160, y=268))

    def _draw_connecting(self, surface: pygame.Surface) -> None:
        _spinner(surface, 160, 230, time.monotonic() - self._spin_t)
        ssid = self._target.ssid if self._target else ""
        msg  = theme.render(f"Connecting to {ssid}…", 12, theme.WHITE, max_width=290)
        surface.blit(msg, msg.get_rect(centerx=160, y=256))

    def _draw_done(self, surface: pygame.Surface) -> None:
        cx, cy = 160, 210
        pygame.draw.circle(surface, (40, 180, 100), (cx, cy), 34)
        pts = [(cx - 16, cy), (cx - 4, cy + 14), (cx + 17, cy - 14)]
        pygame.draw.lines(surface, theme.WHITE, False, pts, 3)

        msg_s = theme.render(self._message, 13, theme.WHITE, bold=True, max_width=290)
        surface.blit(msg_s, msg_s.get_rect(centerx=160, y=260))

        if self._ip:
            ip_s = theme.render(self._ip, 12, theme.ACCENT)
            surface.blit(ip_s, ip_s.get_rect(centerx=160, y=286))

    def _draw_error(self, surface: pygame.Surface) -> None:
        cx, cy = 160, 210
        pygame.draw.circle(surface, (180, 60, 60), (cx, cy), 34)
        pygame.draw.line(surface, theme.WHITE, (cx - 14, cy - 14), (cx + 14, cy + 14), 3)
        pygame.draw.line(surface, theme.WHITE, (cx + 14, cy - 14), (cx - 14, cy + 14), 3)

        msg_s = theme.render(self._message, 11, theme.WHITE, max_width=290)
        surface.blit(msg_s, msg_s.get_rect(centerx=160, y=260))

    def _draw_unsupported(self, surface: pygame.Surface) -> None:
        msg1 = theme.render("WiFi control is available", 14, theme.WHITE, bold=True)
        msg2 = theme.render("on the device (Pi) only.", 14, theme.DIM)
        surface.blit(msg1, msg1.get_rect(centerx=160, y=218))
        surface.blit(msg2, msg2.get_rect(centerx=160, y=248))

    # ── scroll ────────────────────────────────────────────────────────────────

    def _clamp_scroll(self) -> None:
        if self._sel < self._scroll:
            self._scroll = self._sel
        elif self._sel >= self._scroll + MAX_VIS:
            self._scroll = self._sel - MAX_VIS + 1


# ── drawing helpers ───────────────────────────────────────────────────────────

def _spinner(surface: pygame.Surface, cx: int, cy: int, t: float) -> None:
    import math
    for i in range(8):
        angle = math.pi * 2 * i / 8 - t * 4
        alpha = (i + 1) / 8
        col   = tuple(int(v * alpha) for v in theme.ACCENT)
        ox    = cx + int(10 * math.cos(angle))
        oy    = cy + int(10 * math.sin(angle))
        pygame.draw.circle(surface, col, (ox, oy), 2)


def _signal_bars(
    surface: pygame.Surface, cx: int, cy: int, signal: int, col: tuple
) -> None:
    """4-bar signal strength indicator."""
    heights = [4, 7, 10, 13]
    for i, h in enumerate(heights):
        filled = signal >= (i + 1) * 25
        c      = col if filled else tuple(max(0, v - 80) for v in col)
        x      = cx + i * 5 - 8
        pygame.draw.rect(surface, c, (x, cy - h // 2, 4, h), border_radius=1)


def _lock(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    pygame.draw.rect(surface, col, (cx - 5, cy - 2, 10, 8), border_radius=2)
    pygame.draw.arc(surface, col,
                    pygame.Rect(cx - 4, cy - 8, 8, 8), 0, 3.14159, 2)


def _scrollbar(
    surface: pygame.Surface,
    x: int, y: int, h: int,
    total: int, scroll: int, vis: int,
) -> None:
    pygame.draw.rect(surface, (30, 30, 44), (x, y, 2, h), border_radius=1)
    thumb_h = max(16, int(h * vis / total))
    thumb_y = y + int((h - thumb_h) * scroll / max(1, total - vis))
    pygame.draw.rect(surface, theme.DIM, (x, thumb_y, 2, thumb_h), border_radius=1)
