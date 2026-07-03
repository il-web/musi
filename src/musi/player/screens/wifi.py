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
from musi.player.keyboard import Keyboard
from musi.player.mpd_client import PlayerStatus
from musi.player.screen import Screen
from musi.player.widgets import KineticList, PendingTap, draw_scrollbar

# ── layout ────────────────────────────────────────────────────────────────────
LIST_Y  = 64
ITEM_H  = 50
NAV_Y   = 456
MAX_VIS = (NAV_Y - LIST_Y) // ITEM_H   # 7
KB_TOP  = 318                          # on-screen keyboard (password entry)

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


def _nmcli(args: list, timeout: float) -> subprocess.CompletedProcess:
    """Run nmcli; on a polkit denial retry via passwordless sudo.

    The app runs as a systemd user service, which polkit does not treat as an
    active local session, so device control can be denied. install.sh grants
    the user NOPASSWD sudo for nmcli as the fallback path.
    """
    r = subprocess.run(["nmcli", *args],
                       capture_output=True, text=True, timeout=timeout)
    err = (r.stderr or "").lower()
    if r.returncode != 0 and any(s in err for s in (
            "not authorized", "insufficient privileges",
            "permission denied", "access denied")):
        r = subprocess.run(["sudo", "-n", "nmcli", *args],
                           capture_output=True, text=True, timeout=timeout)
    return r


class WifiScreen(Screen):
    animates = True   # scan/connect spinners — full FPS, no sleep

    def __init__(self, app) -> None:
        super().__init__(app)
        self._state:    str            = _S_SCANNING
        self._networks: list[_Network] = []
        self._sel:      int            = 0
        self._klist = KineticList(ITEM_H, NAV_Y - LIST_Y)
        self._tap   = PendingTap()

        # password entry
        self._target:   _Network | None = None
        self._password: str             = ""
        self._kb:       Keyboard        = Keyboard(KB_TOP)
        self._pwd_t:    float           = 0.0     # last char typed (peek timer)

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
            self._pwd_t = time.monotonic()
            return True
        return False

    # ── touch input ──────────────────────────────────────────────────────────

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if self._state == _S_LIST and LIST_Y <= y < NAV_Y - 24 \
                and not self._tap.pending:
            di = self._klist.index_at(y - LIST_Y)
            if 0 <= di < len(self._networks):
                self._sel = di                # highlight flashes, then opens
                self._tap.set(lambda: self._handle_list(Button.SELECT))
                return None
        if self._state == _S_PASSWORD:
            if y >= KB_TOP:                       # tap on the on-screen keyboard
                self._on_key(self._kb.key_at(x, y))
                return None
            if y < 26:                            # status bar = cancel
                self._state = _S_LIST
            return None
        if self._state in (_S_DONE, _S_ERROR, _S_UNSUPPORTED):
            return Button.BACK                    # tap anywhere to dismiss
        return super().handle_touch(x, y)

    def handle_scroll(self, dy: float) -> None:
        if self._state == _S_LIST:
            self._klist.scroll_by(dy)

    def handle_scroll_start(self) -> None:
        self._klist.start_touch()

    def handle_scroll_end(self) -> None:
        self._klist.end_touch()

    def _on_key(self, key: "str | None") -> None:
        if key is None:
            return
        if key == "ENTER":
            self._do_connect()
        elif key == "BACKSPACE":
            self._password = self._password[:-1]
        elif key == "SPACE":
            self._password += " "
        elif len(key) == 1:
            self._password += key
            self._pwd_t = time.monotonic()

    # ── button input ─────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if self._state == _S_LIST:
            self._handle_list(button)
        elif self._state == _S_PASSWORD:
            self._handle_password(button)
        elif self._state in (_S_DONE, _S_UNSUPPORTED):
            if button == Button.BACK:
                self.app.pop()
        elif self._state == _S_ERROR:
            if button == Button.BACK:
                self._state = _S_LIST   # back to the list to retry
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
                    self._kb.layer = 0
                    self._kb.shift = False
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
        # typing comes via handle_event (real keyboard) or _on_key (on-screen)
        if button == Button.BACK:
            if self._password:
                self._password = self._password[:-1]
            else:
                self._state = _S_LIST
        elif button == Button.PLAY_PAUSE:
            self._do_connect()

    # ── scan ─────────────────────────────────────────────────────────────────

    def _scan(self) -> None:
        try:
            # SSID requested LAST so ":" inside a network name can't shift the
            # other fields (split is limited to the first three separators).
            r = _nmcli(
                ["-t", "-f", "IN-USE,SIGNAL,SECURITY,SSID",
                 "device", "wifi", "list", "--rescan", "yes"],
                timeout=25,
            )
            if r.returncode != 0:
                self._message = (r.stderr.strip() or r.stdout.strip()
                                 or "WiFi scan failed")[:80]
                self._state   = _S_ERROR
                return
            nets: list[_Network] = []
            seen: set[str] = set()
            for line in r.stdout.strip().splitlines():
                parts = line.split(":", 3)
                if len(parts) < 4:
                    continue
                in_use, sig, sec, ssid = parts
                ssid = ssid.replace("\\:", ":").strip()   # nmcli -t escapes ':'
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
            self._klist.set_count(len(nets), reset=True)
            self._state    = _S_LIST
        except Exception as exc:
            self._message = str(exc)
            self._state   = _S_ERROR

    # ── connect ──────────────────────────────────────────────────────────────

    def _do_connect(self) -> None:
        if not self._target:
            return
        if self._target.secured and not self._password:
            return   # secured network needs a password before connecting
        self._state = _S_CONNECTING
        net = self._target
        pwd = self._password
        threading.Thread(target=self._connect_thread, args=(net, pwd), daemon=True).start()

    def _connect_thread(self, net: _Network, password: str) -> None:
        args = ["device", "wifi", "connect", net.ssid]
        if net.secured and password:
            args += ["password", password]
        try:
            r = _nmcli(args, timeout=45)
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
                # a failed attempt leaves a broken profile behind — remove it
                # so the next try starts clean (only when we sent a password)
                if net.secured and password:
                    try:
                        _nmcli(["connection", "delete", "id", net.ssid], timeout=10)
                    except Exception:
                        pass
                raw = (r.stderr.strip() or r.stdout.strip() or "Connection failed")
                self._message = ("Wrong password" if "secret" in raw.lower()
                                 else raw[:80])
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

        self._klist.update()
        self._tap.update()
        first = self._klist.first_visible()
        shift = self._klist.pixel_shift()
        clip  = surface.get_clip()
        surface.set_clip(pygame.Rect(0, LIST_Y, 320, NAV_Y - LIST_Y))
        for vi in range(self._klist.visible_rows()):
            di = first + vi
            if di >= len(self._networks):
                break
            net = self._networks[di]
            y   = LIST_Y + vi * ITEM_H - shift
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

        surface.set_clip(clip)
        draw_scrollbar(surface, 314, LIST_Y, NAV_Y - LIST_Y, self._klist)

    def _draw_password(self, surface: pygame.Surface) -> None:
        # target SSID
        net_s = theme.render(
            f"Password for {self._target.ssid}" if self._target else "Password",
            13, theme.WHITE, bold=True, max_width=296,
        )
        surface.blit(net_s, net_s.get_rect(centerx=160, y=64))

        # password box
        box_rect = pygame.Rect(8, 92, 304, 42)
        pygame.draw.rect(surface, (28, 28, 42), box_rect, border_radius=6)
        pygame.draw.rect(surface, theme.ACCENT, box_rect, 1, border_radius=6)

        # mask with bullets; briefly show the last typed char (phone-style peek)
        t      = time.monotonic()
        cursor = "|" if int(t * 2) % 2 == 0 else " "
        if self._password and (t - self._pwd_t) < 1.0:
            shown = "•" * (len(self._password) - 1) + self._password[-1]
        else:
            shown = "•" * len(self._password)
        pwd_s = theme.render(shown + cursor, 14, theme.WHITE, max_width=290)
        surface.blit(pwd_s, (18, box_rect.y + (42 - pwd_s.get_height()) // 2))

        hint = theme.render("✓ = connect   ·   tap top bar = cancel", 10, theme.DIM)
        surface.blit(hint, hint.get_rect(centerx=160, y=146))

        # ── on-screen keyboard ────────────────────────────────────────────────
        self._kb.draw(surface)

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
        self._klist.ensure_visible(self._sel)


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


