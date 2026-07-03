"""OS hardening controls: storage lock (overlay root) + Wi-Fi power save.

Storage lock = Raspberry Pi OS's overlay filesystem: the SD card is mounted
read-only and all writes go to a RAM overlay that vanishes on reboot, so a
hard power cut can never corrupt the card. While locked, anything that needs
to persist (OTA updates, music uploads, play history, new WiFi/BT pairings)
silently doesn't — the UI blocks those flows and points at Settings → Power.

Toggling uses ``raspi-config nonint do_overlayfs`` (0 = enable, 1 = disable),
allowed passwordless via the sudoers rule install.sh installs. Enabling
rebuilds the initramfs, which takes minutes on a Zero W — call set_overlay()
from a background thread. Either direction only takes effect after a reboot.

On a dev machine every probe returns False and set_overlay() fails cleanly.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_CMDLINE_PATHS = ("/boot/firmware/cmdline.txt", "/boot/cmdline.txt")

_active: bool | None = None   # overlay state is fixed for the whole boot


def overlay_active() -> bool:
    """True if / is currently an overlay (this boot is running locked)."""
    global _active
    if _active is None:
        _active = False
        try:
            for line in Path("/proc/mounts").read_text().splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "/" and parts[2] == "overlay":
                    _active = True
                    break
        except OSError:
            pass
    return _active


def overlay_configured() -> bool:
    """True if the NEXT boot will be locked (boot=overlay in cmdline.txt)."""
    for p in _CMDLINE_PATHS:
        try:
            return "boot=overlay" in Path(p).read_text()
        except OSError:
            continue
    return False


def set_overlay(enable: bool) -> tuple[bool, str]:
    """Configure the storage lock for the next boot. Blocks for minutes when
    enabling (initramfs rebuild) — run in a thread. Returns (ok, message)."""
    arg = "0" if enable else "1"   # raspi-config nonint: 0 = yes/enable
    try:
        r = subprocess.run(
            ["sudo", "-n", "raspi-config", "nonint", "do_overlayfs", arg],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        return False, "raspi-config not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as exc:
        return False, str(exc)
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip().splitlines()
        return False, out[-1] if out else f"failed (exit {r.returncode})"
    return True, "Reboot to apply"


def wifi_powersave(on: bool) -> None:
    """Toggle Wi-Fi power save for this boot (default-on via NetworkManager
    config; the transfer screen turns it off so uploads run at full speed)."""
    try:
        subprocess.run(
            ["sudo", "-n", "iw", "dev", "wlan0", "set", "power_save",
             "on" if on else "off"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass
