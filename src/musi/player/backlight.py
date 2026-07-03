"""Panel backlight control via sysfs.

The ST7796 panel overlay (``backlight-gpio=12``) registers a binary
gpio-backlight device under /sys/class/backlight/; writing 0 / max to its
``brightness`` file switches the LED rail on and off.

Writing needs group access — install.sh ships a udev rule that makes
``brightness`` group-writable by ``video``. Without it (or on a dev machine
with no sysfs) every call is a safe no-op and set_on() returns False, so the
app falls back to blanking the framebuffer only.
"""
from __future__ import annotations

from pathlib import Path

_dev:      Path | None = None
_max:      int         = 1
_searched: bool        = False


def _find() -> Path | None:
    global _dev, _max, _searched
    if not _searched:
        _searched = True
        for d in sorted(Path("/sys/class/backlight").glob("*")):
            try:
                _max = int((d / "max_brightness").read_text().strip())
                _dev = d
                break
            except (OSError, ValueError):
                continue
    return _dev


def available() -> bool:
    """True if a controllable backlight device exists."""
    return _find() is not None


def set_on(on: bool) -> bool:
    """Switch the backlight on/off. Returns True if the write succeeded."""
    dev = _find()
    if dev is None:
        return False
    try:
        (dev / "brightness").write_text(str(_max if on else 0))
        return True
    except OSError:
        return False
