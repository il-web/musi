"""WiFi status for the status bar — cheap /sys + /proc reads, cached.

Unlike audio_detect this needs no subprocess or thread: operstate and
/proc/net/wireless are plain file reads (microseconds), so a cached
inline read from the draw path is fine.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_CACHE_S = 5.0
_last: float = -999.0
_state: tuple[bool, int] = (False, 0)   # (connected, strength 0-3)

_OPERSTATE = Path("/sys/class/net/wlan0/operstate")
_WIRELESS  = Path("/proc/net/wireless")


def wifi_status() -> tuple[bool, int]:
    """Return (connected, strength 0-3). Never blocks meaningfully."""
    global _last, _state
    now = time.monotonic()
    if now - _last >= _CACHE_S:
        _last = now
        _state = _read()
    return _state


def _read() -> tuple[bool, int]:
    if sys.platform == "win32":
        return (True, 3)   # dev machine: assume online, render the full icon

    try:
        if _OPERSTATE.read_text().strip() != "up":
            return (False, 0)
    except OSError:
        return (False, 0)

    # /proc/net/wireless "link" quality column is 0–70
    try:
        for line in _WIRELESS.read_text().splitlines():
            if line.strip().startswith("wlan0:"):
                quality = float(line.split()[2].rstrip("."))
                if quality >= 45:
                    return (True, 3)
                if quality >= 25:
                    return (True, 2)
                return (True, 1)
    except (OSError, ValueError, IndexError):
        pass
    return (True, 2)   # up but no quality info — show medium
