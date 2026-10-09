"""Bluetooth device manager screen.

Lists paired devices, scans for nearby ones, and lets the user pair /
connect / disconnect — all by touch (or the physical UP/DOWN/SELECT
buttons).  Every bluetoothctl call runs in a daemon thread so the UI
never freezes.

On non-Linux platforms (Windows dev machine) the screen shows a
friendly "available on device only" notice.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass

import pygame

from musi.player import audio_detect, icons, statusbar, theme
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus
from musi.player.list_screen import ListScreen

SCAN_RECT = pygame.Rect(10, 50, 300, 30)   # "Scan for devices" button
LIST_Y = 88      # first device card top
ITEM_H = 64      # height per device card
NAV_Y  = 456

# Written before a user-initiated disconnect so musi-bt-router knows not to
# fight it with its auto-reconnect watchdog.
USER_DISCONNECT_FLAG = "/tmp/musi-bt-user-disconnect"

CONNECT_ATTEMPTS = 3     # speakers fresh out of power-on often fail the first try
CONNECT_RETRY_S  = 2.0

SCAN_S          = 12     # discovery length
SCAN_REFRESH_S  = 2.5    # how often the list refreshes while scanning
MAX_INFO_PROBES = 15     # unnamed devices checked per refresh (one call each)


@dataclass
class _Device:
    mac:       str
    name:      str
    paired:    bool = True
    connected: bool = False


class BluetoothScreen(ListScreen):

    def __init__(self, app) -> None:
        super().__init__(app, item_h=ITEM_H, list_y=LIST_Y, nav_y=NAV_Y)
        self._devices:    list[_Device] = []
        self._info_msg:   str  = ""     # loading / error / empty text
        self._action_msg: str  = ""     # "Connecting…", "Connected", etc.
        self._busy:       bool = False  # block input while an action runs
        self._scanning:   bool = False  # discovery in progress
        self._audio_seen: dict[str, bool] = {}   # mac → audio? (unnamed devices)

        # static surfaces
        self._header_surf: pygame.Surface | None = None
        self._nav_surf:    pygame.Surface | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_enter(self) -> None:
        self._refresh()

    # ── draw ──────────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        if self._header_surf is None:
            self._header_surf = theme.render("Bluetooth", 16, theme.WHITE, bold=True)
            self._nav_surf    = theme.render(
                "Tap Scan to search · tap a device to pair/connect", 10, theme.DIM,
                max_width=300,
            )

        surface.fill(theme.BG)
        statusbar.draw(surface, status, audio_detect.get_audio_type(), show_home=len(self.app.stack) > 1)

        # section header
        surface.blit(self._header_surf, (14, 26))

        # ── scan button ───────────────────────────────────────────────────────
        scan_bg = theme.ACCENT if self._scanning else theme.CARD_BG
        pygame.draw.rect(surface, scan_bg, SCAN_RECT, border_radius=8)
        scan_label = "Scanning…" if self._scanning else "Scan for devices"
        ls = theme.render(scan_label, 12, theme.WHITE, bold=True)
        surface.blit(ls, ls.get_rect(center=SCAN_RECT.center))

        if self._info_msg:
            msg = theme.render(self._info_msg, 12, theme.DIM, max_width=290)
            surface.blit(msg, (14, LIST_Y))
        else:
            # _fetch fills _devices on a worker thread; the scroll model learns
            # the new length here, on the UI thread. Without this it stayed at
            # 0 rows, so a long device list could never be scrolled.
            if self._klist.count != len(self._devices):
                self._klist.set_count(len(self._devices))
            self.draw_list_viewport(surface, len(self._devices))

        # action message (bottom, above nav)
        if self._action_msg:
            am = theme.render(self._action_msg, 11, theme.ACCENT, max_width=290)
            surface.blit(am, am.get_rect(centerx=160, y=NAV_Y - 22))

        surface.blit(self._nav_surf, self._nav_surf.get_rect(centerx=160, y=NAV_Y))

    def _draw_row(self, surface: pygame.Surface, y: int, di: int) -> None:
        dev = self._devices[di]
        sel  = (di == self._sel)
        bg   = theme.ACCENT if sel else theme.CARD_BG
        rect = pygame.Rect(10, y, 300, ITEM_H - 4)

        pygame.draw.rect(surface, bg, rect, border_radius=8)

        # BT glyph
        gcol = theme.WHITE if sel else theme.DIM
        icons.draw_bt_glyph(surface, 36, y + (ITEM_H - 4) // 2, gcol)

        # device name
        name_s = theme.render(dev.name, 13, theme.WHITE, bold=sel, max_width=220)
        surface.blit(name_s, (58, y + 10))

        # status badge
        if dev.connected:
            badge_col = (120, 230, 140) if not sel else theme.WHITE
            badge_s   = theme.render("● Connected", 10, badge_col)
        elif dev.paired:
            badge_col = theme.DIM if not sel else (220, 220, 230)
            badge_s   = theme.render("○ Tap to connect", 10, badge_col)
        else:
            badge_col = theme.ACCENT if not sel else (220, 220, 230)
            badge_s   = theme.render("＋ Tap to pair", 10, badge_col)
        surface.blit(badge_s, (58, y + 32))

        # chevron
        ccol = theme.WHITE if sel else theme.CARD_BG
        icons.draw_chevron_right(surface, 302, y + (ITEM_H - 4) // 2, ccol)

    # ── input ─────────────────────────────────────────────────────────────────

    def handle(self, button: Button, status: PlayerStatus) -> None:
        if self._busy:
            return
        if button == Button.UP:
            self._sel = max(0, self._sel - 1)
        elif button == Button.DOWN:
            self._sel = min(len(self._devices) - 1, max(0, self._sel + 1))
        elif button == Button.SELECT and self._devices:
            self._activate(self._devices[self._sel])
        elif button == Button.BACK:
            self.app.pop()

    def handle_touch(self, x: int, y: int) -> "Button | None":
        if y < 26:
            return Button.HOME
        if SCAN_RECT.collidepoint(x, y):
            self._scan()
            return None
        if not self._info_msg:
            if LIST_Y <= y < NAV_Y - 20 and not self._tap.pending:
                di = self._klist.index_at(y - LIST_Y)
                if 0 <= di < len(self._devices):
                    self._sel = di
                    if not self._busy and not self._scanning:
                        self._tap.set(lambda: self._activate(self._devices[self._sel]))
                    return None
        return super().handle_touch(x, y)

    # ── internal ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._devices  = []
        self._sel      = 0
        self._info_msg = "Loading devices…"
        threading.Thread(target=self._fetch, daemon=True).start()

    def _scan(self) -> None:
        if self._scanning or self._busy:
            return
        self._scanning   = True
        self._action_msg = ""
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self) -> None:
        """Discover for SCAN_S seconds, refreshing the list as devices appear.

        A discovery left running by a crashed client, or wedged in the Pi 3's
        combo chip, makes every new scan fail with org.bluez.Error.InProgress.
        Recovery escalates: stop that scan and retry, then power-cycle the
        radio and retry. Whatever still fails is shown, not swallowed.
        """
        try:
            _bt("power", "on")
            err = self._run_scan()
            if err and "InProgress" in err:
                self._action_msg = "Clearing a stuck scan…"
                _bt("scan", "off")
                err = self._run_scan()
            if err and "InProgress" in err:
                self._action_msg = "Restarting the Bluetooth radio…"
                _bt("power", "off")
                time.sleep(1.5)
                _bt("power", "on")
                err = self._run_scan()
            self._action_msg = f"Scan failed: {_short(err)}" if err else ""
        except FileNotFoundError:
            self._info_msg = "bluetoothctl not found — install bluez."
        except Exception as exc:
            self._action_msg = f"Scan failed: {exc}"
        finally:
            self._scanning = False
        self._fetch()

    def _run_scan(self) -> str:
        """One discovery run. Returns '' on success, else bluetoothctl's error.

        bluetoothctl exits at once when discovery can't start, and otherwise
        keeps scanning until --timeout — so a quick exit means failure.
        """
        proc = subprocess.Popen(
            ["bluetoothctl", "--timeout", str(SCAN_S), "scan", "on"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + SCAN_S + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(SCAN_REFRESH_S)
            self._fetch()                       # devices appear as they're found
        if proc.poll() is None:
            proc.kill()
        out = proc.communicate()[0] or ""
        # "Failed to start discovery: org.bluez.Error.InProgress" — matched on
        # the prefix, so a device *named* "Error" can't look like a failure
        failed = [ln for ln in out.splitlines() if ln.strip().startswith("Failed to")]
        return failed[-1].strip() if failed else ""

    def _fetch(self) -> None:
        if sys.platform == "win32":
            self._info_msg = "Bluetooth control is available on the device (Pi) only."
            return

        try:
            paired = self._list_devices("Paired")
            nearby = self._list_devices(None)
        except FileNotFoundError:
            self._info_msg = "bluetoothctl not found — install bluez."
            return
        except Exception as exc:
            self._info_msg = f"Error: {exc}"
            return

        paired_macs = {mac for mac, _ in paired}
        devices: list[_Device] = []

        # paired devices first (with live connection state)
        for mac, name in paired:
            devices.append(
                _Device(mac=mac, name=name, paired=True, connected=self._is_connected(mac))
            )

        # then nearby unpaired devices: named ones, plus unnamed ones that say
        # they're audio. Headphones (AirPods especially) are often seen before
        # their name resolves; other nameless devices are beacons — skip those.
        probes = 0
        for mac, name in nearby:
            if mac in paired_macs:
                continue
            if _is_bare_address(name, mac):
                # a busy street has dozens of nameless beacons: ask about each
                # address once, not on every refresh
                if mac not in self._audio_seen:
                    if probes >= MAX_INFO_PROBES:
                        continue
                    probes += 1
                    self._audio_seen[mac] = self._is_audio(mac)
                if not self._audio_seen[mac]:
                    continue
                name = f"Audio device · {mac[-5:]}"
            devices.append(_Device(mac=mac, name=name, paired=False, connected=False))

        self._devices  = devices
        self._sel      = min(self._sel, max(0, len(devices) - 1))
        self._info_msg = "" if devices else "No devices yet. Tap Scan to search."

    def _list_devices(self, kind: str | None) -> list[tuple[str, str]]:
        cmd = ["bluetoothctl", "devices"]
        if kind:
            cmd.append(kind)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
        out: list[tuple[str, str]] = []
        for line in r.stdout.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device":
                mac  = parts[1]
                name = parts[2] if len(parts) == 3 else mac
                out.append((mac, name))
        return out

    def _is_audio(self, mac: str) -> bool:
        try:
            r = subprocess.run(["bluetoothctl", "info", mac],
                               capture_output=True, text=True, timeout=4)
        except Exception:
            return False
        return _looks_like_audio(r.stdout)

    def _is_connected(self, mac: str) -> bool:
        try:
            r = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True, text=True, timeout=4,
            )
            return "Connected: yes" in r.stdout
        except Exception:
            return False

    def _activate(self, dev: _Device) -> None:
        if dev.paired:
            self._toggle(dev)
        else:
            self._pair(dev)

    def _pair(self, dev: _Device) -> None:
        self._action_msg = f"Pairing {dev.name}…"
        self._busy       = True

        def _run() -> None:
            try:
                subprocess.run(
                    ["bluetoothctl", "--timeout", "25", "pair", dev.mac],
                    capture_output=True, text=True, timeout=30,
                )
                dev.paired = True
                connected = self._connect_verified(dev)
                self._action_msg = (
                    f"Connected to {dev.name}" if connected
                    else f"Paired {dev.name} — tap to connect"
                )
                audio_detect._last_started = -999.0
            except Exception as exc:
                self._action_msg = f"Pairing failed: {exc}"
            finally:
                self._busy = False

        threading.Thread(target=_run, daemon=True).start()

    def _toggle(self, dev: _Device) -> None:
        disconnecting = dev.connected
        self._action_msg = f"{'Disconnecting' if disconnecting else 'Connecting'} {dev.name}…"
        self._busy       = True

        def _run() -> None:
            try:
                if disconnecting:
                    # tell the router this drop is intentional — no auto-reconnect
                    try:
                        with open(USER_DISCONNECT_FLAG, "w") as f:
                            f.write(dev.mac)
                    except OSError:
                        pass
                    subprocess.run(
                        ["bluetoothctl", "disconnect", dev.mac],
                        capture_output=True, timeout=15,
                    )
                    dev.connected = self._is_connected(dev.mac)
                    self._action_msg = (
                        f"Disconnected from {dev.name}" if not dev.connected
                        else f"Couldn't disconnect {dev.name}"
                    )
                else:
                    connected = self._connect_verified(dev)
                    self._action_msg = (
                        f"Connected to {dev.name}" if connected
                        else f"Couldn't connect — is {dev.name} turned on?"
                    )
                audio_detect._last_started = -999.0
            except Exception as exc:
                self._action_msg = f"Failed: {exc}"
            finally:
                self._busy = False

        threading.Thread(target=_run, daemon=True).start()

    def _connect_verified(self, dev: _Device) -> bool:
        """Connect with retries and report the REAL state.

        Adapter power-on + trust come first: an untrusted device is dropped
        by bluetoothd seconds after connecting (the classic 'connects then
        disconnects itself'), and pairing done from the speaker side never
        set trust.
        """
        subprocess.run(["bluetoothctl", "power", "on"],
                       capture_output=True, timeout=6)
        subprocess.run(["bluetoothctl", "trust", dev.mac],
                       capture_output=True, timeout=6)

        for attempt in range(CONNECT_ATTEMPTS):
            if attempt:
                self._action_msg = (
                    f"Connecting {dev.name}… (retry {attempt + 1}/{CONNECT_ATTEMPTS})"
                )
                time.sleep(CONNECT_RETRY_S)
            subprocess.run(
                ["bluetoothctl", "connect", dev.mac],
                capture_output=True, timeout=20,
            )
            if self._is_connected(dev.mac):
                dev.connected = True
                return True

        dev.connected = self._is_connected(dev.mac)
        return dev.connected


# ── helpers ───────────────────────────────────────────────────────────────────

def _bt(*args: str) -> None:
    subprocess.run(["bluetoothctl", *args], capture_output=True, timeout=8)


def _is_bare_address(name: str, mac: str) -> bool:
    """bluez names an unnamed device after its address (AA-BB-… or AA:BB:…)."""
    return name.replace(":", "").replace("-", "").upper() == mac.replace(":", "").upper()


def _looks_like_audio(info: str) -> bool:
    """From `bluetoothctl info`: an audio icon, or an A2DP sink / headset UUID."""
    return ("Icon: audio-" in info or "Audio Sink" in info
            or "Headset" in info or "Handsfree" in info)


def _short(err: str) -> str:
    """'Failed to start discovery: org.bluez.Error.InProgress' → 'InProgress'."""
    tail = err.rsplit("org.bluez.Error.", 1)
    return tail[1] if len(tail) == 2 else err
