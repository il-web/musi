"""Non-blocking audio-output type detection (Bluetooth vs wired vs unknown).

Detection runs in a background daemon thread so the pygame loop is never
stalled.  Results are cached for _INTERVAL seconds.
"""
from __future__ import annotations

import platform
import subprocess
import sys
import threading
import time

# ── module state ──────────────────────────────────────────────────────────────
_lock          = threading.Lock()
_audio_type:   str   = "unknown"
_last_started: float = -999.0
_INTERVAL             = 15.0      # seconds between background re-checks

# On Windows suppress the console flash when spawning PowerShell
_POPEN_FLAGS: dict = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


# ── public API ────────────────────────────────────────────────────────────────

def get_audio_type() -> str:
    """Return 'bluetooth', 'wired', or 'unknown'.  Never blocks."""
    global _last_started
    now = time.monotonic()
    with _lock:
        due = (now - _last_started) >= _INTERVAL
    if due:
        with _lock:
            _last_started = now
        threading.Thread(target=_run, daemon=True).start()
    with _lock:
        return _audio_type


# ── internal ──────────────────────────────────────────────────────────────────

def _run() -> None:
    global _audio_type
    result = _detect()
    with _lock:
        _audio_type = result


def _detect() -> str:
    if sys.platform == "win32":
        return _windows()
    return _linux()


def _windows() -> str:
    """Query the active Windows audio playback devices via WMI."""
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-WmiObject Win32_SoundDevice | "
                "Where-Object {$_.StatusInfo -eq 3}).Name",
            ],
            capture_output=True, text=True, timeout=6,
            **_POPEN_FLAGS,
        )
        name = r.stdout.lower()
        if "bluetooth" in name or " bt " in name:
            return "bluetooth"
        if name.strip():
            return "wired"
    except Exception:
        import logging
        logging.warning('Ignored exception', exc_info=True)
    return "unknown"


def _linux() -> str:
    """Detect BT via bluetoothctl or pactl; fall back to ALSA for wired."""
    # 1 — bluetoothctl: quick check for a connected device
    try:
        r = subprocess.run(
            ["bluetoothctl", "info"],
            capture_output=True, text=True, timeout=3,
        )
        if "Audio Sink" in r.stdout or "Connected: yes" in r.stdout:
            return "bluetooth"
    except Exception:
        import logging
        logging.warning('Ignored exception', exc_info=True)

    # 2 — PulseAudio / PipeWire: check sinks
    try:
        r = subprocess.run(
            ["pactl", "list", "sinks"],
            capture_output=True, text=True, timeout=3,
        )
        if "bluetooth" in r.stdout.lower():
            return "bluetooth"
        if r.returncode == 0 and r.stdout.strip():
            return "wired"
    except Exception:
        import logging
        logging.warning('Ignored exception', exc_info=True)

    # 3 — ALSA only (bare Pi with no PulseAudio)
    try:
        r = subprocess.run(
            ["aplay", "-l"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return "wired"
    except Exception:
        import logging
        logging.warning('Ignored exception', exc_info=True)

    return "unknown"
